from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Contract:
    id: str
    predicate: str
    paths: tuple[str, ...]
    probe: Literal["keyed", "unkeyed"]
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if self.probe not in ("keyed", "unkeyed") or not 0 < self.timeout <= 60:
            raise ValueError("Invalid probe or timeout")
        if not self.paths or any(
            not path or Path(path).is_absolute() or ".." in Path(path).parts for path in self.paths
        ):
            raise ValueError("Contract paths must be repository-relative files")


@dataclass(frozen=True)
class Project:
    id: str
    repository: Path
    contracts: tuple[Contract, ...]


_PROBE = """
import importlib.util
import json
from pathlib import Path
import sys
from fastapi.testclient import TestClient

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location("job_api", root / "job_api.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
headers = {"Idempotency-Key": "stable-demo-key"} if sys.argv[2] == "keyed" else {}
with TestClient(module.app) as client:
    first = client.post("/jobs", json={"task": "demo"}, headers=headers)
    second = client.post("/jobs", json={"task": "demo"}, headers=headers)
    jobs = client.get("/jobs")
    first.raise_for_status()
    second.raise_for_status()
    jobs.raise_for_status()
    ids = [first.json()["id"], second.json()["id"]]
    count = len(jobs.json())
    if count == 2 and ids[0] != ids[1]:
        duplicates = True
    elif count == 1 and ids[0] == ids[1]:
        duplicates = False
    else:
        raise RuntimeError("Unexpected job API response")
    print(json.dumps({"duplicates": duplicates, "job_ids": ids, "job_count": count}))
"""


def config_digest(contract: Contract) -> str:
    definition = json.dumps(asdict(contract), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((definition + "\n" + _PROBE).encode()).hexdigest()


class Repository:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(self.path), *args],
            capture_output=True,
            check=True,
            timeout=15,
        )

    def resolve(self, revision: str) -> str:
        if not revision or revision.startswith("-") or "\x00" in revision:
            raise ValueError("Invalid Git revision")
        try:
            return (
                self._git("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
                .stdout.decode()
                .strip()
            )
        except subprocess.CalledProcessError as error:
            raise ValueError(f"Unknown commit: {revision}") from error

    def ancestor(self, base: str, target: str) -> bool:
        base, target = self.resolve(base), self.resolve(target)
        try:
            self._git("merge-base", "--is-ancestor", base, target)
            return True
        except subprocess.CalledProcessError as error:
            if error.returncode == 1:
                return False
            raise

    def changed(self, base: str, target: str, paths: tuple[str, ...] = ()) -> tuple[str, ...]:
        base, target = self.resolve(base), self.resolve(target)
        if not self.ancestor(base, target):
            raise ValueError("The base revision must be an ancestor of the target")
        output = self._git(
            "diff", "--name-only", "--no-renames", "-z", base, target, "--", *paths
        ).stdout
        return tuple(path.decode() for path in output.split(b"\x00") if path)

    def run(self, revision: str, contract: Contract) -> dict:
        sha = self.resolve(revision)
        evidence = dict(
            outcome="unknown",
            reason="",
            stdout="",
            stderr="",
            exit_code=None,
            revision=sha,
            config_digest=config_digest(contract),
        )
        try:
            archive = self._git("archive", "--format=tar", sha).stdout
            with tempfile.TemporaryDirectory(prefix="premise-check-") as directory:
                root = Path(directory)
                with tarfile.open(fileobj=io.BytesIO(archive)) as files:
                    files.extractall(root, filter="data")
                for name in (*contract.paths, "job_api.py"):
                    file = root / name
                    if not file.is_file() or not file.resolve().is_relative_to(root):
                        evidence["reason"] = f"Required file is missing: {name}"
                        return evidence
                with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                    try:
                        result = subprocess.run(
                            [sys.executable, "-I", "-c", _PROBE, str(root), contract.probe],
                            cwd=root,
                            stdout=stdout,
                            stderr=stderr,
                            timeout=contract.timeout,
                        )
                        evidence["exit_code"] = result.returncode
                    except subprocess.TimeoutExpired:
                        evidence["reason"] = "Check timed out"
                    stdout.seek(0)
                    stderr.seek(0)
                    evidence["stdout"] = stdout.read(8193).decode(errors="replace")
                    evidence["stderr"] = stderr.read(8192).decode(errors="replace")
                if evidence["reason"]:
                    return evidence
                if evidence["exit_code"] != 0:
                    evidence["reason"] = "Check process failed"
                    return evidence
                try:
                    observation = json.loads(evidence["stdout"])
                    duplicates = observation["duplicates"]
                    if type(duplicates) is not bool:
                        raise ValueError("Expected a boolean observation")
                except (ValueError, KeyError, TypeError):
                    evidence["reason"] = "Check returned invalid output"
                    return evidence
                evidence["outcome"] = "true" if duplicates else "false"
                evidence["reason"] = (
                    f"Repeated {contract.probe} requests created {observation['job_count']} job(s)"
                )
        except (OSError, subprocess.SubprocessError, tarfile.TarError) as error:
            evidence["reason"] = f"Check could not complete: {type(error).__name__}"
        return evidence
