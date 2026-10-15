# Revision memory

## Sub-features

Record a decision, retrieve it, and inspect evidence at a Git revision.

## How to get to it (user POV)

Open the dashboard and use the View revision selector.
Select a decision card to inspect its scope, assumptions, sources, and history.

## Driving it with the browser

Select r1 in `View revision`.
Confirm both seeded decisions are supported.
Select r2 before running its checks.
Confirm both decisions need revalidation.
Confirm stale evidence still displays the r1 SHA.
Use `+ Record decision` to exercise the creation form.
Select at least one supporting assumption before submitting.

## Gotchas

The selector shows a tag and an abbreviated SHA.
Record actual option values from the current DOM.
The seed script does not erase previous r2 checks.
Use a new graph prefix for a fresh initial state.
