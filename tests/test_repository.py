import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from premise.demo import create_demo
from premise.repository import Repository, config_digest


@pytest.fixture
def project(tmp_path):
    return create_demo(tmp_path / "demo")


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit_change(project, suffix: str) -> str:
    source = project.repository / "job_api.py"
    source.write_text(source.read_text() + suffix)
    git(project.repository, "add", "job_api.py")
    git(project.repository, "commit", "-m", "Test failed check")
    return git(project.repository, "rev-parse", "HEAD")


def test_real_api_at_both_revisions_preserves_checkout(project):
    repo = Repository(project.repository)
    head = repo.resolve("HEAD")
    source = project.repository / "job_api.py"
    source.write_text(source.read_text() + "\n# Uncommitted work must survive checks.\n")
    working_copy = source.read_text()
    outcomes = {}
    for revision in ("r1", "r2"):
        for contract in project.contracts:
            result = repo.run(revision, contract)
            outcomes[revision, contract.probe] = result["outcome"]
            assert result["revision"] == repo.resolve(revision)
            assert result["exit_code"] == 0
            observed = json.loads(result["stdout"])
            assert observed["job_count"] == (2 if result["outcome"] == "true" else 1)
    assert outcomes == {
        ("r1", "keyed"): "true",
        ("r1", "unkeyed"): "true",
        ("r2", "keyed"): "false",
        ("r2", "unkeyed"): "true",
    }
    assert repo.resolve("HEAD") == head
    assert source.read_text() == working_copy


def test_revision_resolution_diff_and_ancestry(project):
    repo = Repository(project.repository)
    assert len(repo.resolve("r1")) == 40
    assert repo.ancestor("r1", "r2")
    assert not repo.ancestor("r2", "r1")
    assert repo.changed("r1", "r2") == ("job_api.py",)
    assert repo.changed("r1", "r1") == ()
    assert repo.changed("r1", "r2", ("unrelated.py",)) == ()
    with pytest.raises(ValueError, match="ancestor"):
        repo.changed("r2", "r1")
    for invalid in ("--help", "", "not-a-revision"):
        with pytest.raises(ValueError):
            repo.resolve(invalid)


def test_demo_setup_is_idempotent_and_preserves_existing_files(project, tmp_path):
    repo = Repository(project.repository)
    revisions = repo.resolve("r1"), repo.resolve("r2")
    assert create_demo(project.repository) == project
    assert (repo.resolve("r1"), repo.resolve("r2")) == revisions
    existing = tmp_path / "owned"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="Refusing"):
        create_demo(existing)
    assert (existing / "keep.txt").read_text() == "keep"


def test_missing_contract_file_is_unknown(project):
    contract = replace(project.contracts[0], paths=("missing.py",))
    result = Repository(project.repository).run("r2", contract)
    assert result["outcome"] == "unknown"
    assert result["reason"] == "Required file is missing: missing.py"
    assert result["exit_code"] is None


@pytest.mark.parametrize(
    ("suffix", "timeout", "reason"),
    [
        ('\nraise RuntimeError("probe cannot import app")\n', 5.0, "Check process failed"),
        ('\nprint("not valid probe output")\n', 5.0, "Check returned invalid output"),
        ("\nimport time\ntime.sleep(30)\n", 0.2, "Check timed out"),
    ],
)
def test_failed_checks_are_unknown(project, suffix, timeout, reason):
    revision = commit_change(project, suffix)
    result = Repository(project.repository).run(
        revision, replace(project.contracts[0], timeout=timeout)
    )
    assert result["outcome"] == "unknown"
    assert result["reason"] == reason


def test_contract_configuration_is_validated_and_hashed(project):
    contract = project.contracts[0]
    assert config_digest(contract) == config_digest(contract)
    assert config_digest(contract) != config_digest(
        replace(contract, predicate="Changed expectation")
    )
    assert config_digest(contract) != config_digest(replace(contract, paths=("other.py",)))
    for paths in ((), ("../outside.py",), ("/absolute.py",), ("",)):
        with pytest.raises(ValueError):
            replace(contract, paths=paths)
    with pytest.raises(ValueError):
        replace(contract, probe="arbitrary-command")
