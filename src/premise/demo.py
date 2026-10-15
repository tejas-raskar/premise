from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from premise.repository import Contract, Project, Repository

_R1 = """from fastapi import FastAPI, Header

app = FastAPI()
jobs = []

@app.post("/jobs")
def create_job(body: dict, idempotency_key: str | None = Header(default=None)):
    job = {"id": len(jobs) + 1, "task": body["task"]}
    jobs.append(job)
    return job

@app.get("/jobs")
def list_jobs():
    return jobs
"""
_R2 = (
    _R1.replace("jobs = []", "jobs = []\nkeys = {}")
    .replace(
        '    job = {"id": len(jobs) + 1, "task": body["task"]}',
        "    if idempotency_key is not None and idempotency_key in keys:\n"
        "        return keys[idempotency_key]\n"
        '    job = {"id": len(jobs) + 1, "task": body["task"]}',
    )
    .replace(
        "    jobs.append(job)",
        "    jobs.append(job)\n    if idempotency_key is not None:\n"
        "        keys[idempotency_key] = job",
    )
)


def demo_project(path: Path) -> Project:
    return Project(
        "demo",
        path.resolve(),
        tuple(
            Contract(
                id=f"{kind}-duplicates",
                predicate=f"Repeated {kind} requests create duplicate jobs",
                paths=("job_api.py",),
                probe=kind,
            )
            for kind in ("keyed", "unkeyed")
        ),
    )


def create_demo(path: Path = Path(".artifacts/demo-repo")) -> Project:
    path = Path(path).resolve()
    if path.exists():
        marker = path / ".git" / "premise-demo"
        if not marker.is_file() or marker.read_text() != "1\n":
            raise ValueError(f"Refusing to replace an existing directory: {path}")
        repo = Repository(path)
        repo.resolve("r1")
        repo.resolve("r2")
        return demo_project(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".premise-demo-", dir=path.parent) as temporary:
        staging = Path(temporary) / "repo"
        staging.mkdir()

        def git(*args: str) -> None:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(staging),
                    "-c",
                    "user.name=Premise Demo",
                    "-c",
                    "user.email=demo@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    *args,
                ],
                check=True,
                capture_output=True,
                timeout=15,
            )

        git("init", "--initial-branch=main")
        for tag, source in (("r1", _R1), ("r2", _R2)):
            (staging / "job_api.py").write_text(source)
            git("add", "job_api.py")
            git(
                "commit",
                "-m",
                "Create job API" if tag == "r1" else "Deduplicate requests with a stable key",
            )
            git("tag", tag)
        (staging / ".git" / "premise-demo").write_text("1\n")
        staging.rename(path)
    return demo_project(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the two-revision synthetic job API")
    parser.add_argument("path", nargs="?", type=Path, default=Path(".artifacts/demo-repo"))
    project = create_demo(parser.parse_args().path)
    repo = Repository(project.repository)
    print(f"Repository: {project.repository}\nr1: {repo.resolve('r1')}\nr2: {repo.resolve('r2')}")


if __name__ == "__main__":
    main()
