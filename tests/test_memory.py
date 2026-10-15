from __future__ import annotations

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from premise.memory import Memory
from premise.models import MemoryError, RecordDecision, evaluate_supports
from premise.repository import Project, Repository


def decision_body(**changes):
    return {
        "project": "demo",
        "request_id": uuid4().hex,
        "revision": "r1",
        "statement": "Do not retry job creation requests",
        "scope": "jobs",
        "sources": [],
        "supports": [[{"contract": "keyed-duplicates", "expected": True}]],
        **changes,
    }


def check(instance, revision="r1", contract="keyed-duplicates", **changes):
    return instance.run_check(
        {
            "project": "demo",
            "request_id": uuid4().hex,
            "revision": revision,
            "contract": contract,
            **changes,
        }
    )


def view(instance, decision_id, revision="r1"):
    return instance.recall({"project": "demo", "revision": revision, "decision_id": decision_id})[
        "decisions"
    ][0]


def add_commit(project, name, content="Documentation only\n"):
    (project.repository / name).write_text(content)
    for args in (
        ("add", name),
        (
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            name,
        ),
    ):
        subprocess.run(
            ["git", "-C", str(project.repository), *args], check=True, capture_output=True
        )
    return Repository(project.repository).resolve("HEAD")


def test_revision_history_impact_and_receipts(memory):
    instance, project = memory
    body = decision_body()
    recorded = instance.record_decision(body)
    old = recorded["decision"]["id"]
    assert recorded["decision"]["status"] == "unknown"
    assert check(instance)["outcome"] == "true"
    original = view(instance, old)
    assert original["status"] == "supported"
    assert view(instance, old, "r2")["status"] == "needs_revalidation"
    impact_body = {"project": "demo", "request_id": "impact", "base": "r1", "target": "r2"}
    impact = instance.assess_changes(impact_body)
    assert impact["changed_paths"] == ["job_api.py"]
    assert impact["affected"] == [
        {
            "decision_id": old,
            "contract_id": "keyed-duplicates",
            "path": ["job_api.py", "keyed-duplicates", f"{old}:support:0", old],
        }
    ]
    assert instance.assess_changes(impact_body) == impact
    assert check(instance, "r2")["outcome"] == "false"
    current = view(instance, old, "r2")
    assert current["status"] == "contradicted"
    assert [e["freshness"] for e in current["evidence"]] == ["stale", "direct"]
    assert view(instance, old) == original
    assert instance.record_decision(body) == recorded
    prefix = next(iter(instance._graphs.values())).name.rsplit("_", 1)[0]
    restarted = Memory([project], graph_prefix=prefix)
    assert restarted.record_decision(body) == recorded
    assert view(restarted, old, "r2") == current
    with pytest.raises(MemoryError, match="different payload"):
        restarted.record_decision({**body, "statement": "Different decision"})


def test_unchanged_evidence_and_no_change_assessment(memory):
    instance, project = memory
    old = instance.record_decision(decision_body(revision="r2"))["decision"]["id"]
    check(instance, "r2")
    target = add_commit(project, "README.md")
    result = view(instance, old, target)
    assert result["status"] == "contradicted"
    assert result["evidence"][0]["observed_sha"] == Repository(project.repository).resolve("r2")
    assert result["evidence"][0]["freshness"] == "inherited"
    assessment = instance.assess_changes(
        {"project": "demo", "request_id": "unchanged", "base": "r2", "target": target}
    )
    assert assessment["affected"] == []
    assert (
        instance.assess_changes(
            {"project": "demo", "request_id": "same", "base": target, "target": target}
        )["changed_paths"]
        == []
    )


def test_conjunctive_and_alternative_support(memory):
    instance, _ = memory
    keyed = {"contract": "keyed-duplicates", "expected": True}
    unkeyed = {"contract": "unkeyed-duplicates", "expected": True}
    conjunction = instance.record_decision(decision_body(supports=[[keyed, unkeyed]]))["decision"][
        "id"
    ]
    alternative = instance.record_decision(decision_body(supports=[[keyed], [unkeyed]]))[
        "decision"
    ]["id"]
    check(instance, "r2")
    assert view(instance, conjunction, "r2")["status"] == "contradicted"
    assert view(instance, alternative, "r2")["status"] == "unknown"
    assert check(instance, "r2", "unkeyed-duplicates")["outcome"] == "true"
    assert view(instance, conjunction, "r2")["status"] == "contradicted"
    assert view(instance, alternative, "r2")["status"] == "supported"
    assert (
        evaluate_supports(
            [[keyed, unkeyed]],
            {"keyed-duplicates": ("true", "direct"), "unkeyed-duplicates": ("unknown", "stale")},
        )
        == "needs_revalidation"
    )


def test_proposals_are_inactive_and_acceptance_is_revision_scoped(memory):
    instance, _ = memory
    old = instance.record_decision(decision_body())["decision"]["id"]
    check(instance)
    proposal_body = decision_body(
        revision="r2",
        replaces=old,
        reason="Stable key prevents duplicates",
        supports=[[{"contract": "keyed-duplicates", "expected": False}]],
    )
    with pytest.raises(MemoryError, match="same scope"):
        instance.propose_replacement({**proposal_body, "scope": "other"})
    proposed = instance.propose_replacement(proposal_body)
    replacement = proposed["replacement"]["id"]
    assert proposed["replacement"]["state"] == "proposed"
    assert view(instance, old, "r2")["superseded_by"] is None
    acceptance = {"project": "demo", "request_id": "accept", "proposal_id": proposed["proposal_id"]}
    with pytest.raises(MemoryError, match="must be supported"):
        instance.accept_proposal(acceptance)
    check(instance, "r2")
    accepted = instance.accept_proposal(acceptance)
    assert instance.accept_proposal(acceptance) == accepted
    assert instance.propose_replacement(proposal_body) == proposed
    assert view(instance, old, "r2")["status"] == "superseded"
    assert view(instance, replacement, "r2")["state"] == "active"
    assert view(instance, old)["status"] == "supported"
    assert (
        instance.recall({"project": "demo", "revision": "r1", "decision_id": replacement})[
            "decisions"
        ]
        == []
    )
    with pytest.raises(MemoryError, match="already has"):
        instance.accept_proposal({**acceptance, "request_id": "accept-again"})


def test_pending_and_unknown_checks_block_previous_success(memory, monkeypatch):
    instance, project = memory
    old = instance.record_decision(decision_body(revision="r2"))["decision"]["id"]
    check(instance, "r2")
    target = add_commit(project, "README.md")
    assert view(instance, old, target)["status"] == "contradicted"
    started, release = threading.Event(), threading.Event()

    def unfinished(revision, contract):
        started.set()
        assert release.wait(5)
        return {
            "outcome": "unknown",
            "reason": "Check timed out",
            "stdout": "",
            "stderr": "",
            "exit_code": None,
        }

    monkeypatch.setattr(instance._repos["demo"], "run", unfinished)
    body = {
        "project": "demo",
        "request_id": "pending",
        "revision": target,
        "contract": "keyed-duplicates",
    }
    with ThreadPoolExecutor() as executor:
        future = executor.submit(instance.run_check, body)
        assert started.wait(5)
        try:
            pending = instance.run_check(body)
            assert pending["outcome"] == "unknown"
            assert view(instance, old, target)["status"] == "unknown"
        finally:
            release.set()
        assert future.result()["reason"] == "Check timed out"
    assert view(instance, old, target)["status"] == "unknown"
    assert instance.run_check(body)["reason"] == "Check timed out"


def test_conflicting_observations_are_unknown_without_changing_evidence(memory, monkeypatch):
    instance, _ = memory
    old = instance.record_decision(decision_body())["decision"]["id"]
    check(instance)
    original = view(instance, old)["evidence"][0]
    monkeypatch.setattr(
        instance._repos["demo"],
        "run",
        lambda *args: {
            "outcome": "false",
            "reason": "A conflicting observation",
            "stdout": "false",
            "stderr": "",
            "exit_code": 0,
        },
    )
    check(instance)
    result = view(instance, old)
    assert result["status"] == "unknown"
    assert result["evidence"][0] == original
    assert [e["outcome"] for e in result["evidence"]] == ["true", "false"]
    assert "Conflicting definitive" in result["resolution_reason"]


def test_project_isolation_and_configuration_identity(memory):
    instance, project = memory
    instance.record_decision(decision_body())
    other = Project("second", project.repository, project.contracts)
    prefix = next(iter(instance._graphs.values())).name.rsplit("_", 1)[0]
    isolated = Memory([other], graph_prefix=prefix)
    try:
        assert isolated.recall({"project": "second", "revision": "r1"})["decisions"] == []
    finally:
        isolated._graphs["second"].delete()
    changed = replace(project, contracts=(replace(project.contracts[0], timeout=1),))
    with pytest.raises(MemoryError, match="configuration changed"):
        Memory([changed], graph_prefix=prefix)


def test_invalid_input_and_revision_boundaries(memory):
    instance, _ = memory
    for changes in (
        {"supports": []},
        {"arbitrary_command": "echo unsafe"},
        {"supports": [[{"contract": "keyed-duplicates", "expected": "true"}]]},
    ):
        with pytest.raises(ValidationError):
            RecordDecision.model_validate(decision_body(**changes))
    with pytest.raises(MemoryError, match="Unknown contract"):
        instance.record_decision(
            decision_body(supports=[[{"contract": "missing", "expected": True}]])
        )
    with pytest.raises(MemoryError, match="Unknown commit"):
        instance.record_decision(decision_body(revision="missing"))
    with pytest.raises(MemoryError, match="base must"):
        instance.assess_changes(
            {"project": "demo", "request_id": "reverse", "base": "r2", "target": "r1"}
        )
    assert instance.recall({"project": "demo", "revision": "r1"})["decisions"] == []


def test_support_relationships_are_the_read_source(memory):
    instance, _ = memory
    old = instance.record_decision(decision_body())["decision"]["id"]
    stored = instance._graphs["demo"].ro_query("MATCH (d:Decision) RETURN d.data").result_set[0][0]
    assert "supports" not in json.loads(stored)
    check(instance)
    assert view(instance, old)["supports"] == [[{"contract": "keyed-duplicates", "expected": True}]]


def test_concurrent_duplicate_records_write_once(memory):
    instance, _ = memory
    body = decision_body(request_id="concurrent")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(instance.record_decision, [body, body]))
    assert results[0] == results[1]
    assert len(instance.recall({"project": "demo", "revision": "r1"})["decisions"]) == 1


def test_unfinished_check_reservation_survives_restart(memory, monkeypatch):
    instance, project = memory
    old = instance.record_decision(decision_body())["decision"]["id"]
    check(instance)

    class ProcessStopped(BaseException):
        pass

    def stopped(*args):
        raise ProcessStopped()

    monkeypatch.setattr(instance._repos["demo"], "run", stopped)
    request = {
        "project": "demo",
        "request_id": "unfinished",
        "revision": "r1",
        "contract": "keyed-duplicates",
    }
    with pytest.raises(ProcessStopped):
        instance.run_check(request)
    prefix = next(iter(instance._graphs.values())).name.rsplit("_", 1)[0]
    restarted = Memory([project], graph_prefix=prefix)
    assert restarted.run_check(request)["reason"] == "Check is unfinished"
    assert view(restarted, old)["status"] == "unknown"
    assert [e["outcome"] for e in view(restarted, old)["evidence"]] == ["true", "unknown"]
