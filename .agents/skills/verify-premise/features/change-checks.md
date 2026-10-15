# Change checks

## Sub-features

Trace file dependencies and store measured contract results.

## How to get to it (user POV)

Select r2 and compare from r1.
Use Trace changes, then select an affected decision.

## Driving it with the browser

Click `Trace changes`.
Confirm `job_api.py` connects through Contract and Support to Decision.
Click `Run check keyed-duplicates` on the keyed decision.
Confirm the result is false and reports one job.
Click `Run check unkeyed-duplicates` on the unkeyed decision.
Confirm the result is true and reports two jobs.
Expand Check output to inspect the measured job IDs.

## Gotchas

The visible button text is Run check; its accessible name includes the contract ID.
False means the duplicate predicate failed. It does not mean the process failed.
An empty path result does not prove that no effects exist.
