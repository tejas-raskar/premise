# Demo

Complete the README setup first.
The seed script records two decisions at r1 and runs their checks.
Repeated requests create duplicate jobs at that revision.

## Three-minute flow

1. Open the dashboard.
2. Select r1.
3. Inspect the keyed and unkeyed decisions.
4. Read each check's original revision and measured job count.
5. Select r2.
6. Assess changes from r1 to r2.
7. Follow the file, contract, support, and decision path.
8. Run both contract checks at r2.
9. Inspect the keyed result. Repeated requests now create one job.
10. Inspect the unkeyed result. Repeated requests still create two jobs.
11. Propose a keyed replacement with the expected duplicate result set to false.
12. Use this statement: "Retry keyed job requests only with the same stable idempotency key."
13. Accept the supported proposal.
14. Confirm that the unkeyed restriction remains active.
15. Select r1 again.
16. Confirm that the original decisions and evidence remain intact.

The initial r2 state requires revalidation. A file change alone proves no contradiction.
A proposal does not change active advice until acceptance.

## MCP client flow

With the server running, execute:

```sh
uv run python scripts/demo_agent.py
```

This deterministic client calls the real MCP tools.
It proposes a replacement only when the check results support that replacement.
It leaves acceptance to the dashboard.
It does not run an LLM or edit repository code.

## Track evidence

- Track 1: graph traversal selects affected decisions and the checks that an agent must run.
- Track 2: separate sessions reuse persistent decisions, observations, and scoped replacements.
- Track 3: revision-pinned sources explain engineering decisions and preserve their history.

Tracks 1 and 2 are the primary targets.
The MVP does not ingest company chats or ticket systems.
