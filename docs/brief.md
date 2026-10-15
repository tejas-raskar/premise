# MVP brief

Premise stores engineering decisions with their assumptions and evidence.
It identifies decisions that need new checks when related code changes.

## Required behavior

1. Record a decision with its assumptions, source references, and revision.
2. Retrieve the decision from a later agent session.
3. Follow graph relationships from changed code to affected decisions.
4. Mark affected decisions for revalidation in the target revision.
5. Run a configured check and store its result as evidence.
6. Propose a scoped replacement decision. Preserve the old decision.
7. Show the dependency path, evidence, and history in a dashboard.

The MCP server and the HTTP API use the same application functions.
The existing coding agent supplies reasoning and code edits.
Premise supplies graph context and check results.

## Demonstration

Use a synthetic job API at two Git revisions.
The first revision creates duplicate jobs after repeated requests.
The second revision supports a stable idempotency key.
A later session checks the old retry restriction and proposes a narrower rule.
Unkeyed requests must retain the restriction.

## Verification

- Use a real FalkorDB instance for graph integration tests.
- Check unchanged, changed, contradicted, and superseded decisions.
- Check that old revisions retain their original evidence.
- Check conjunctive requirements and alternative support.
- Check duplicate writes and separate project graphs.
- Exercise the MCP tools through a real MCP client.
- Exercise the dashboard in a browser.
- Preserve unknown results when a check cannot complete.

## Limits

The MVP uses one configured repository per project.
It uses explicit links between contracts and code paths.
It runs configured checks. It does not accept arbitrary shell commands.
It does not include general code indexing, vector search, or remote repository execution.
It does not include a hosted account system or paid services.

## Delivery

Create ordered local commits after verified milestones.
Keep setup, architecture, graph, tool, and demo documents brief.
Disclose AI assistance and verification limits.
Target hackathon Tracks 1 and 2. Link engineering sources for Track 3.
