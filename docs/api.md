# Interface contract

The HTTP API and MCP tools share these request bodies.
HTTP routes use `POST /api/{tool_name}`.
Unknown fields produce validation errors.
Revision inputs resolve to full commit SHAs.

| Tool | Required fields |
| --- | --- |
| `record_decision` | project, request_id, revision, statement, scope, sources, supports |
| `recall` | project, revision; optional decision_id |
| `assess_changes` | project, request_id, base, target |
| `run_check` | project, request_id, revision, contract |
| `propose_replacement` | project, request_id, revision, replaces, statement, scope, reason, sources, supports |

`sources` contains `{uri, note}` objects.
`supports` contains nonempty groups of `{contract, expected}` requirements.
Requirements within a group use AND. Groups use OR.

`GET /api/projects` returns `{projects: [{id, revisions: [{name, sha}], contracts: [{id, predicate, paths}]}]}`.
`POST /api/accept_proposal` accepts `{project, request_id, proposal_id}`.
Acceptance is a dashboard action, not an MCP tool.

## Responses

- Record: `{decision: DecisionView}`.
- Recall: `{revision, decisions: DecisionView[]}`.
- Assess: `{assessment_id, base, target, changed_paths, affected: Impact[]}`.
- Check: `{run_id, revision, contract, outcome, reason, exit_code, stdout, stderr}`.
- Propose: `{proposal_id, replaces, replacement: DecisionView, state: "proposed"}`.
- Accept: `{proposal_id, state: "accepted", revision}`.

`DecisionView` contains id, statement, scope, introduced_sha, at_sha, status, sources, supports, evidence, history, and superseded_by.
It also contains `state: active | proposed` and optional `proposal_id`.
Status is supported, needs_revalidation, contradicted, unknown, or superseded.
Evidence contains id, contract, observed_sha, outcome, freshness, reason, stdout, stderr, and exit_code.
Freshness is direct, inherited, stale, or missing.
History contains kind, id, and revision.
Impact contains decision_id, contract_id, and path.
Paths list File, Contract, Support, and Decision IDs in traversal order.

Errors use `{error: {code, message}}` with an appropriate HTTP status.
An incomplete check returns unknown evidence, not a successful assertion.
Mutation retries return the stored response. Use recall to obtain current status.
