# Service-mode harness diagnostic experiment

This fixed probe is diagnostic only. It cannot approve a delivery, replace Red
or Green, change a snapshot, authorize another revision, or reset retry limits.

`broker/service_mode_harness_spike.py` extracts the literal Node harness through
Python AST without importing the test module. It checks the expected frozen test
hash, executes the unchanged harness, reports only structural facts and fixed
text comparisons, and verifies both input hashes again. Execute it in a
credential-free, network-disabled, read-only disposable Compose-labelled job,
with the frozen candidate mounted read-only. Do not run untrusted fixtures on
the host. The runtime image must be pinned. Private operational receipts remain
outside Git.

## Observed diagnostic result

The initial suspicion that the report lacked `after_ok.calls` or returned an
object instead of text was **not confirmed** by the actual frozen candidate.
Partial helper inspection was insufficient: the driver constructs its own
`after_ok` record and `modeText()` returns a string in this revision.

The unchanged runtime report instead showed:

- `after_ok.calls = 4` and `pending_observed.calls = 4`.
- `after_ok` already contains “Checking environment…” but is not yet Demo.
- The deferred scenario eventually contains “Demo environment”.

Source inspection explains two test-contract problems. The first scenario
captures `after_ok` synchronously before `await flush()`, then later requires
that old captured value to be the terminal Demo value. Its request counter
counts all startup requests, not only service-mode requests. These observations
do not prove that every functional failure is a harness defect or that the
implementation is correct.

## Required next transition

The current trial remains blocked after two test-revision generations. Preserve
the failed author status, immutable Red, review and full-suite evidence. Feed
the source-bound experiment to an independent technical diagnostic/replanning
path; do not silently authorize a third recursive child. Any approved new test
plan must retain loading-state, exact response matching, accessibility, one
service-mode request per load, no polling, and all existing board regression
coverage. An implementation still needs genuine TDD, independent review and
full-suite validation before product PR, CI, deployment and same-SHA QA.
