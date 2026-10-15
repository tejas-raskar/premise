# Replacement

## Sub-features

Propose a decision, require support, accept it, and preserve earlier evidence.

## How to get to it (user POV)

Select the keyed decision at r2 after its check completes.
Click Propose replacement.

## Driving it with the browser

Enter a retry rule that requires the same stable idempotency key.
Enter the reason for replacement.
Set `Expected keyed-duplicates in support set 1` to `Must be false`.
Click Save proposal.
Confirm the proposal is supported but inactive.
Click Accept proposal.
Confirm the old keyed decision is superseded.
Confirm the unkeyed decision remains supported and active.
Select r1 and confirm the original keyed decision is supported.

## Gotchas

The replacement scope is read-only.
Acceptance evaluates support at the proposal's revision.
Acceptance must not appear in the earlier revision's history.
