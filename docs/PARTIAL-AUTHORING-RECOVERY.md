# Partial test authoring after a validation timeout

The fixed executor records bounded per-case start/end/duration diagnostics through
`validation_trace.py`, a read-only wrapper around the **unchanged pinned suite**.
Its digest belongs to the job identity and its mount/command are checked. It does
not change assertions, discovery, test timeouts, skips, exit codes or verdicts.
Events are sandbox observations, never delivery evidence. An incomplete report
cannot qualify Red, Green, controls or approval. Legacy reports remain readable.

Browser contract 2 uses a recorded cumulative runtime budget:
`max(project.timeout_seconds, min(240, 30 + 3 * acceptance_case_count))`.
This is a whole-job ceiling, not an assertion timeout or permission to retry.
Unit-only jobs retain the configured budget. Native worker limits remain intact.
The controller still stops and archives overdue jobs and never restarts an
identical failed job. Quality retains the exact failed-job receipt even if the
agent catches the tool error; recovery prioritizes that underlying failure over
the later generic missing-handoff message.

## One assisted continuation, without a new graph

`authoring_recovery.resume_partial` is an operator-only maintenance operation.
It requires a verified source, drained pause, the exact current tests-author
triage, completed CTO hold, unchanged candidate and an actual pre-repair timeout
receipt. The original baseline/product must be byte-identical and all candidate
changes additive test files. Existing Red/review/freeze requires another recovery
path. Completed predecessors are preserved and downstream work must be unstarted.
The release must already be classified as assisted.

The durable admission precedes the native triage transition. Replaying it is
idempotent; another attempt or a changed graph/workspace cannot be mistaken for
the admitted source. No body, retry counter, graph, test or workspace is reset.
The author receives the original candidate and explicit guidance to complete
behavioral coverage. An absence of results before actions does not prove tie or
hand-result rules. Fresh Red and independent review/freezing remain mandatory,
followed by all implementation, CI, deployment and QA gates. A further failure
remains subject to native limits; this is not unlimited automatic recovery.

## Qualification boundary

Offline unit tests cover partial output, immutable gate output, failed-job
provenance, foreign-run rejection and retirement without identical restarts.
An isolated Docker execution reproduced the old timeout, then completed the same
62-case candidate with 11 assertion failures, no errors/skips and a complete
report using the bounded budget. Those observations do **not** approve the
candidate tests or substitute for the author's fresh submission and review.
A copied native board demonstrated one same-card continuation with unchanged
workspace, graph and run history, without a model or worker.

This repair does not demonstrate autonomous delivery. The current cycle remains
assisted; a later uninterrupted useful delivery must establish repeatability.
