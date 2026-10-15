# Architecture

Premise uses immutable records and revision-specific views.
FalkorDB stores decisions, support relationships, observations, and replacement history.
Git supplies exact revisions and file changes.
The coding agent supplies reasoning and code edits.

```text
Coding agent → MCP ─┐
                   ├→ Memory → FalkorDB
Dashboard → HTTP ──┘         → Git and configured checks
```

Use one Python process with one mutation lock per project.
Use a separate graph for each configured project.
Run checks in separate temporary directories.
The client cannot select a command or repository path.

## Records

The dependency path is `Decision → Support → Contract → File`.
Each requirement contains a contract and its expected Boolean value.
All requirements in one support must match.
One matching support is sufficient for a decision.

Checks produce true, false, or unknown observations.
A changed file makes previous evidence stale. It does not disprove an assumption.
Reuse ancestor evidence only when all declared files and the check definition match.
An exact-revision unknown result prevents fallback to previous success.
Conflicting definitive results at one revision produce unknown.
Retain each observation's original revision.

A decision has an explicit scope label.
A replacement must have the same scope.
Scope labels do not prove semantic equivalence.
A proposal remains inactive until a user accepts it.
Acceptance requires supported assumptions and no previous accepted replacement.
Earlier revision views exclude later acceptances.
Views show current knowledge about a revision, not historical database snapshots.

## Boundaries

- `repository.py`: Git revisions, file changes, and configured checks.
- `memory.py`: graph queries, persistent records, and revision views.
- `models.py`: validated inputs and support evaluation.
- `server.py`: HTTP and MCP adapters.
- `ui/`: decision, path, evidence, and proposal views.

Use static, parameterized Cypher.
Read queries use `ro_query`.
Each completed mutation and its receipt use one write statement.
Repeated request IDs return stored responses. Different payloads produce a conflict.
Reserve checks before execution. An unfinished reservation remains unknown.

## Implementation checkpoint

1. Blocking steps: select the model, freeze interfaces, and verify the real graph runtime.
2. Independent work: isolate repository checks, memory service, and dashboard files.
3. Shared state: serialize project mutations; isolate check directories and project graphs.
4. Smallest split: one owner per module group; keep both transports on one application core.

The design comparison selected fixed contract predicates over separate claim records.
This keeps the required support logic without a general claim language.
General indexing, contract migrations, and multiple server processes are outside this MVP.
