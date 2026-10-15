---
name: verify-premise
description: Verify Premise through its dashboard, HTTP API, and MCP tools after changes to memory or revision behavior.
---

# Verify Premise

Use the project root as the working directory.
Read [the feature map](features/README.md) before selecting checks.

## Launch

Complete the dependency and dashboard build steps in the root README.
Choose a new graph prefix for each independent verification run.
Use the same prefix for seeding and serving.

```sh
PREMISE_GRAPH_PREFIX=premise_browser_verify uv run python scripts/seed_demo.py
PREMISE_GRAPH_PREFIX=premise_browser_verify uv run uvicorn premise.server:create_app --factory --host 127.0.0.1 --port 8766
```

Record the server process ID.
Do not start a second writer for the same graph.
The server is ready when `/api/projects` returns project `demo` and revisions `r1` and `r2`.

## Doctor

```sh
curl -fsS http://127.0.0.1:8766/api/projects
```

Confirm the response identifies the expected project and revisions.
Check the launch record to confirm port 8766 belongs to this run.

## Drive

Use the T3 preview tools when available.
Open `http://127.0.0.1:8766` and inspect the page before acting.
If preview automation fails twice, use an isolated agent-browser session.
The installed CLI help describes its supported commands.

```sh
agent-browser --session premise-verify open http://127.0.0.1:8766
agent-browser --session premise-verify snapshot -i
```

If Chromium is missing, select an installed executable with `--executable-path` when opening the session.
Close the session before changing that launch option.

Use the accessible controls listed in each feature document.
Verify the complete path from a user action to its visible result.
Do not replace UI actions with internal state setters.
For the MCP path, run `uv run python scripts/demo_agent.py --url http://127.0.0.1:8766/mcp`.
That command writes checks and a proposal to this verification graph.

## Evidence

Save screenshots and action logs under `.artifacts/verification/`.
Capture states before and after acceptance.
Read `/api/recall` to confirm the persisted side effect matches the dashboard.
Use real Git and FalkorDB for this proof.
Mocked results do not prove the demonstration.

## Cleanup

Stop only the server process recorded for this run.
Close the `premise-verify` browser session.
Keep the graph and evidence files for inspection.
Confirm the saved evidence still exists after cleanup.
Do not stop a database or server owned by another run.

## Helpers

`scripts/seed_demo.py` creates initial memory from measured r1 checks.
`scripts/demo_agent.py` exercises the public MCP interface without an LLM.
The README lists the automated test and build commands.
