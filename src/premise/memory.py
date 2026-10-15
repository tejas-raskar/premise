from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import asdict

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from premise.models import (
    AcceptProposal,
    AssessChanges,
    MemoryError,
    ProposeReplacement,
    Recall,
    RecordDecision,
    RunCheck,
    evaluate_supports,
)
from premise.repository import Project, Repository, config_digest


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _id(kind: str) -> str:
    return f"{kind}:{uuid.uuid4().hex}"


class Memory:
    def __init__(
        self, projects: list[Project], host="127.0.0.1", port=6387, graph_prefix="premise"
    ):
        if len({project.id for project in projects}) != len(projects):
            raise ValueError("Project IDs must be distinct")
        self._projects = {project.id: project for project in projects}
        self._repos = {project.id: Repository(project.repository) for project in projects}
        self._locks = {project.id: threading.RLock() for project in projects}
        client = FalkorDB(host=host, port=port, socket_timeout=10, socket_connect_timeout=5)
        self._graphs = {
            project.id: client.select_graph(
                f"{graph_prefix}_{hashlib.sha256(project.id.encode()).hexdigest()[:16]}"
            )
            for project in projects
        }
        for project in projects:
            if len({contract.id for contract in project.contracts}) != len(project.contracts):
                raise ValueError("Contract IDs must be distinct")
            graph = self._graphs[project.id]
            graph.query("MERGE (:Meta {id:'configuration'})", timeout=5000)
            definition = _json(
                {
                    "repository": str(project.repository.resolve()),
                    "contracts": [config_digest(contract) for contract in project.contracts],
                }
            )
            previous = self._read(project.id, "MATCH (m:Meta) RETURN m.definition")
            if previous[0][0] is not None and previous[0][0] != definition:
                raise MemoryError(
                    "conflict", "Project configuration changed. Use a new project.", 409
                )
            graph.query(
                "MATCH (m:Meta) SET m.definition=$definition "
                "WITH m UNWIND $contracts AS c "
                "MERGE (n:Contract {id:c.id}) SET n.data=c.data "
                "WITH n,c UNWIND c.paths AS path "
                "MERGE (f:File {id:path}) MERGE (n)-[:READS]->(f)",
                params={
                    "definition": definition,
                    "contracts": [
                        {"id": c.id, "data": _json(asdict(c)), "paths": list(c.paths)}
                        for c in project.contracts
                    ],
                },
                timeout=5000,
            )
            for label in (
                "Decision",
                "Contract",
                "File",
                "Receipt",
                "Run",
                "Observation",
                "Proposal",
            ):
                try:
                    graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)", timeout=5000)
                except ResponseError as error:
                    if str(error) != "Attribute 'id' is already indexed":
                        raise

    def _project(self, project: str) -> Project:
        if project not in self._projects:
            raise MemoryError("not_found", "Unknown project", 404)
        return self._projects[project]

    def _contract(self, project: str, contract: str):
        for item in self._project(project).contracts:
            if item.id == contract:
                return item
        raise MemoryError("not_found", "Unknown contract", 404)

    def _read(self, project: str, query: str, **params):
        return self._graphs[project].ro_query(query, params=params or None, timeout=5000).result_set

    def _resolve(self, project: str, revision: str) -> str:
        try:
            return self._repos[project].resolve(revision)
        except ValueError as error:
            raise MemoryError("invalid_revision", str(error)) from error

    def _existing(self, operation: str, request):
        digest = hashlib.sha256((operation + _json(request.model_dump())).encode()).hexdigest()
        rows = self._read(
            request.project,
            "MATCH (r:Receipt {id:$id}) RETURN r.hash,r.response",
            id=request.request_id,
        )
        if rows:
            if rows[0][0] != digest:
                raise MemoryError("conflict", "Request ID was used with a different payload", 409)
            return digest, json.loads(rows[0][1])
        return digest, None

    def _commit(self, request, digest: str, response: dict, query: str, **params):
        self._graphs[request.project].query(
            query + " WITH count(*) AS written "
            "CREATE (:Receipt {id:$receipt_id,hash:$hash,response:$response})",
            params={
                **params,
                "receipt_id": request.request_id,
                "hash": digest,
                "response": _json(response),
            },
            timeout=5000,
        )
        return response

    def _snapshot(self, project: str) -> dict:
        snapshot = {
            name: [json.loads(row[0]) for row in self._read(project, query)]
            for name, query in {
                "decisions": "MATCH (n:Decision) RETURN n.data",
                "runs": "MATCH (n:Run) RETURN n.data",
                "observations": "MATCH (n:Observation) RETURN n.data",
                "assessments": "MATCH (n:Assessment) RETURN n.data",
                "proposals": "MATCH (n:Proposal) RETURN n.data",
                "acceptances": "MATCH (n:Acceptance) RETURN n.data",
            }.items()
        }
        supports = {}
        for decision, support, contract, expected in self._read(
            project,
            "MATCH (d:Decision)-[:HAS_SUPPORT]->(s:Support)-[r:REQUIRES]->(c:Contract) "
            "RETURN d.id,s.id,c.id,r.expected ORDER BY s.id,c.id",
        ):
            supports.setdefault(decision, {}).setdefault(support, []).append(
                {"contract": contract, "expected": expected}
            )
        for decision in snapshot["decisions"]:
            groups = supports.get(decision["id"], {})
            decision["supports"] = [
                groups[key] for key in sorted(groups, key=lambda key: int(key.rsplit(":", 1)[1]))
            ]
        return snapshot

    def _decision(self, snapshot: dict, decision: str) -> dict:
        for item in snapshot["decisions"]:
            if item["id"] == decision:
                return item
        raise MemoryError("not_found", "Unknown decision", 404)

    def _evidence(self, project: str, contract_id: str, target: str, snapshot: dict):
        repo, contract = self._repos[project], self._contract(project, contract_id)
        completed = {item["run_id"]: item for item in snapshot["observations"]}
        evidence = []
        resolution_reason = None
        for run in snapshot["runs"]:
            if run["contract"] != contract_id or not repo.ancestor(run["revision"], target):
                continue
            observation = completed.get(
                run["id"],
                {
                    "id": run["id"],
                    "outcome": "unknown",
                    "reason": "Check is unfinished",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                },
            )
            freshness = "direct" if run["revision"] == target else "inherited"
            if run["config_digest"] != config_digest(contract) or (
                freshness == "inherited" and repo.changed(run["revision"], target, contract.paths)
            ):
                freshness = "stale"
            evidence.append(
                {
                    **{
                        key: observation[key]
                        for key in ("id", "outcome", "reason", "stdout", "stderr", "exit_code")
                    },
                    "contract": contract_id,
                    "observed_sha": run["revision"],
                    "freshness": freshness,
                    "_seq": run["seq"],
                }
            )
        candidates = [item for item in evidence if item["freshness"] == "direct"]
        if not candidates:
            for item in evidence:
                if item["freshness"] != "inherited":
                    continue
                if not candidates or repo.ancestor(
                    candidates[0]["observed_sha"], item["observed_sha"]
                ):
                    if not candidates or candidates[0]["observed_sha"] != item["observed_sha"]:
                        candidates = []
                    candidates.append(item)
        if candidates:
            latest = max(candidates, key=lambda item: item["_seq"])
            definitive = {item["outcome"] for item in candidates} - {"unknown"}
            outcome = "unknown" if len(definitive) > 1 else latest["outcome"]
            value = (outcome, latest["freshness"])
            if len(definitive) > 1:
                resolution_reason = (
                    f"Conflicting definitive check results for {contract_id} "
                    f"at {latest['observed_sha']}"
                )
        elif evidence:
            value = ("unknown", "stale")
        else:
            value = ("unknown", "missing")
            evidence.append(
                {
                    "id": f"missing:{contract_id}",
                    "contract": contract_id,
                    "observed_sha": "",
                    "outcome": "unknown",
                    "freshness": "missing",
                    "reason": "No check has run",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                    "_seq": 0,
                }
            )
        evidence.sort(key=lambda item: item.pop("_seq"))
        return value, evidence, resolution_reason

    def _view(self, project: str, decision: dict, target: str, snapshot: dict) -> dict:
        repo = self._repos[project]
        contracts = {item["contract"] for group in decision["supports"] for item in group}
        values, evidence, resolution_reasons = {}, [], []
        for contract in sorted(contracts):
            values[contract], rows, reason = self._evidence(project, contract, target, snapshot)
            evidence.extend(rows)
            if reason:
                resolution_reasons.append(reason)
        proposals = {item["id"]: item for item in snapshot["proposals"]}
        acceptances = [
            item for item in snapshot["acceptances"] if repo.ancestor(item["revision"], target)
        ]
        accepted = {item["proposal_id"] for item in acceptances}
        own_proposal = next(
            (p for p in proposals.values() if p["replacement"] == decision["id"]), None
        )
        replacement = next(
            (
                p["replacement"]
                for p in proposals.values()
                if p["replaces"] == decision["id"] and p["id"] in accepted
            ),
            None,
        )
        history = [
            {"kind": "recorded", "id": decision["id"], "revision": decision["introduced_sha"]}
        ]
        history.extend(
            {"kind": "checked", "id": e["id"], "revision": e["observed_sha"]}
            for e in evidence
            if e["freshness"] != "missing"
        )
        for item in snapshot["assessments"]:
            if decision["id"] in item["decisions"] and repo.ancestor(item["target"], target):
                history.append({"kind": "assessed", "id": item["id"], "revision": item["target"]})
        for proposal in proposals.values():
            if decision["id"] in (proposal["replacement"], proposal["replaces"]) and repo.ancestor(
                proposal["revision"], target
            ):
                history.append(
                    {"kind": "proposed", "id": proposal["id"], "revision": proposal["revision"]}
                )
                history.extend(
                    {"kind": "accepted", "id": item["id"], "revision": item["revision"]}
                    for item in acceptances
                    if item["proposal_id"] == proposal["id"]
                )
        return {
            **{
                key: decision[key]
                for key in ("id", "statement", "scope", "introduced_sha", "sources", "supports")
            },
            "at_sha": target,
            "status": "superseded"
            if replacement
            else evaluate_supports(decision["supports"], values),
            "state": "proposed"
            if own_proposal and own_proposal["id"] not in accepted
            else "active",
            "proposal_id": own_proposal["id"] if own_proposal else None,
            "evidence": evidence,
            "history": history,
            "superseded_by": replacement,
            "resolution_reason": "; ".join(resolution_reasons) or None,
        }

    def projects(self) -> dict:
        projects = []
        for project in self._projects.values():
            revisions = []
            for name in ("r1", "r2"):
                try:
                    revisions.append({"name": name, "sha": self._resolve(project.id, name)})
                except MemoryError:
                    continue
            projects.append(
                {
                    "id": project.id,
                    "revisions": revisions,
                    "contracts": [
                        {"id": c.id, "predicate": c.predicate, "paths": list(c.paths)}
                        for c in project.contracts
                    ],
                }
            )
        return {"projects": projects}

    def recall(self, request: Recall | dict) -> dict:
        request = Recall.model_validate(request)
        self._project(request.project)
        with self._locks[request.project]:
            target = self._resolve(request.project, request.revision)
            snapshot = self._snapshot(request.project)
            decisions = snapshot["decisions"]
            if request.decision_id:
                decisions = [self._decision(snapshot, request.decision_id)]
            decisions = [
                d
                for d in decisions
                if self._repos[request.project].ancestor(d["introduced_sha"], target)
            ]
            return {
                "revision": target,
                "decisions": [self._view(request.project, d, target, snapshot) for d in decisions],
            }

    def _new_decision(self, request: RecordDecision, target: str) -> dict:
        for group in request.supports:
            for requirement in group:
                self._contract(request.project, requirement.contract)
        return {
            "id": _id("decision"),
            "statement": request.statement,
            "scope": request.scope,
            "introduced_sha": target,
            "sources": [source.model_dump() for source in request.sources],
            "supports": [[item.model_dump() for item in group] for group in request.supports],
        }

    @staticmethod
    def _decision_write(decision: dict):
        groups = [
            {"id": f"{decision['id']}:support:{i}", "requirements": group}
            for i, group in enumerate(decision["supports"])
        ]
        return (
            "CREATE (d:Decision {id:$decision_id,data:$decision}) "
            "WITH d UNWIND $groups AS s CREATE (g:Support {id:s.id}) "
            "CREATE (d)-[:HAS_SUPPORT]->(g) WITH g,s "
            "UNWIND s.requirements AS r MATCH (c:Contract {id:r.contract}) "
            "CREATE (g)-[:REQUIRES {expected:r.expected}]->(c)",
            {
                "decision_id": decision["id"],
                "decision": _json({k: v for k, v in decision.items() if k != "supports"}),
                "groups": groups,
            },
        )

    def record_decision(self, request: RecordDecision | dict) -> dict:
        request = RecordDecision.model_validate(request)
        self._project(request.project)
        with self._locks[request.project]:
            digest, existing = self._existing("record_decision", request)
            if existing is not None:
                return existing
            target = self._resolve(request.project, request.revision)
            decision = self._new_decision(request, target)
            response = {
                "decision": self._view(
                    request.project, decision, target, self._snapshot(request.project)
                )
            }
            query, params = self._decision_write(decision)
            return self._commit(request, digest, response, query, **params)

    def assess_changes(self, request: AssessChanges | dict) -> dict:
        request = AssessChanges.model_validate(request)
        self._project(request.project)
        with self._locks[request.project]:
            digest, existing = self._existing("assess_changes", request)
            if existing is not None:
                return existing
            base, target = (
                self._resolve(request.project, request.base),
                self._resolve(request.project, request.target),
            )
            repo = self._repos[request.project]
            if not repo.ancestor(base, target):
                raise MemoryError("invalid_revision", "The base must be an ancestor of the target")
            paths = list(repo.changed(base, target))
            rows = self._read(
                request.project,
                "MATCH (f:File)<-[:READS]-(c:Contract)<-[:REQUIRES]-(s:Support)"
                "<-[:HAS_SUPPORT]-(d:Decision) "
                "WHERE f.id IN $paths RETURN d.id,c.id,s.id,f.id,d.data",
                paths=paths,
            )
            impacts = [
                {"decision_id": d, "contract_id": c, "path": [f, c, s, d]}
                for d, c, s, f, data in rows
                if repo.ancestor(json.loads(data)["introduced_sha"], target)
            ]
            assessment = {
                "id": _id("assessment"),
                "base": base,
                "target": target,
                "decisions": sorted({item["decision_id"] for item in impacts}),
                "changed_paths": paths,
            }
            response = {
                "assessment_id": assessment["id"],
                "base": base,
                "target": target,
                "changed_paths": paths,
                "affected": impacts,
            }
            return self._commit(
                request,
                digest,
                response,
                "CREATE (a:Assessment {id:$id,data:$data}) WITH a UNWIND $decisions AS id "
                "MATCH (d:Decision {id:id}) CREATE (a)-[:AFFECTS]->(d)",
                id=assessment["id"],
                data=_json(assessment),
                decisions=assessment["decisions"],
            )

    def run_check(self, request: RunCheck | dict) -> dict:
        request = RunCheck.model_validate(request)
        self._project(request.project)
        with self._locks[request.project]:
            digest, existing = self._existing("run_check", request)
            if existing is not None:
                return existing
            target = self._resolve(request.project, request.revision)
            contract = self._contract(request.project, request.contract)
            run = {
                "id": _id("run"),
                "revision": target,
                "contract": contract.id,
                "config_digest": config_digest(contract),
                "seq": time.time_ns(),
            }
            pending = {
                "run_id": run["id"],
                "revision": target,
                "contract": contract.id,
                "outcome": "unknown",
                "reason": "Check is unfinished",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
            }
            self._commit(
                request,
                digest,
                pending,
                "MATCH (c:Contract {id:$contract}) CREATE (r:Run {id:$id,data:$data}) "
                "CREATE (r)-[:CHECKS]->(c)",
                contract=contract.id,
                id=run["id"],
                data=_json(run),
            )
        try:
            result = self._repos[request.project].run(target, contract)
        except Exception as error:
            result = {
                "outcome": "unknown",
                "reason": f"Check could not complete: {type(error).__name__}",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
            }
        response = {
            **pending,
            **{key: result[key] for key in ("outcome", "reason", "exit_code", "stdout", "stderr")},
        }
        observation = {**response, "id": _id("evidence")}
        with self._locks[request.project]:
            self._graphs[request.project].query(
                "MATCH (r:Run {id:$run}), (receipt:Receipt {id:$receipt}) "
                "CREATE (o:Observation {id:$id,data:$data}) CREATE (r)-[:RESULT]->(o) "
                "SET receipt.response=$response",
                params={
                    "run": run["id"],
                    "receipt": request.request_id,
                    "id": observation["id"],
                    "data": _json(observation),
                    "response": _json(response),
                },
                timeout=5000,
            )
        return response

    def propose_replacement(self, request: ProposeReplacement | dict) -> dict:
        request = ProposeReplacement.model_validate(request)
        self._project(request.project)
        with self._locks[request.project]:
            digest, existing = self._existing("propose_replacement", request)
            if existing is not None:
                return existing
            target = self._resolve(request.project, request.revision)
            snapshot = self._snapshot(request.project)
            old = self._decision(snapshot, request.replaces)
            old_view = self._view(request.project, old, target, snapshot)
            if not self._repos[request.project].ancestor(old["introduced_sha"], target):
                raise MemoryError(
                    "invalid_revision", "The source decision does not exist at this revision"
                )
            if old_view["state"] != "active" or old_view["superseded_by"]:
                raise MemoryError("conflict", "Only a current active decision can be replaced", 409)
            if old["scope"] != request.scope:
                raise MemoryError("conflict", "A replacement must have the same scope", 409)
            decision = self._new_decision(request, target)
            proposal = {
                "id": _id("proposal"),
                "replaces": old["id"],
                "replacement": decision["id"],
                "revision": target,
                "reason": request.reason,
            }
            snapshot["proposals"].append(proposal)
            response = {
                "proposal_id": proposal["id"],
                "replaces": old["id"],
                "replacement": self._view(request.project, decision, target, snapshot),
                "state": "proposed",
            }
            query, params = self._decision_write(decision)
            query += " WITH count(*) AS written CREATE (:Proposal {id:$proposal_id,data:$proposal})"
            return self._commit(
                request,
                digest,
                response,
                query,
                **params,
                proposal_id=proposal["id"],
                proposal=_json(proposal),
            )

    def accept_proposal(self, request: AcceptProposal | dict) -> dict:
        request = AcceptProposal.model_validate(request)
        self._project(request.project)
        with self._locks[request.project]:
            digest, existing = self._existing("accept_proposal", request)
            if existing is not None:
                return existing
            snapshot = self._snapshot(request.project)
            proposal = next(
                (p for p in snapshot["proposals"] if p["id"] == request.proposal_id), None
            )
            if proposal is None:
                raise MemoryError("not_found", "Unknown proposal", 404)
            target = proposal["revision"]
            old, replacement = (
                self._decision(snapshot, proposal["replaces"]),
                self._decision(snapshot, proposal["replacement"]),
            )
            if old["scope"] != replacement["scope"]:
                raise MemoryError("conflict", "A replacement must have the same scope", 409)
            prior = {a["proposal_id"] for a in snapshot["acceptances"]}
            if any(p["id"] in prior and p["replaces"] == old["id"] for p in snapshot["proposals"]):
                raise MemoryError(
                    "conflict", "The source decision already has an accepted replacement", 409
                )
            if self._view(request.project, replacement, target, snapshot)["status"] != "supported":
                raise MemoryError("conflict", "The replacement assumptions must be supported", 409)
            acceptance = {
                "id": _id("acceptance"),
                "proposal_id": proposal["id"],
                "revision": target,
            }
            response = {"proposal_id": proposal["id"], "state": "accepted", "revision": target}
            return self._commit(
                request,
                digest,
                response,
                "MATCH (p:Proposal {id:$proposal_id}) CREATE (a:Acceptance {id:$id,data:$data}) "
                "CREATE (a)-[:ACCEPTS]->(p)",
                proposal_id=proposal["id"],
                id=acceptance["id"],
                data=_json(acceptance),
            )
