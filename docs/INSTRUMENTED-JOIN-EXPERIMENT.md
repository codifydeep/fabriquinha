# Instrumented join and browser-409 investigation

Status: prepared offline; not a delivery qualification. The provider financial
pause remains in force. No paid calls are required for preparing this experiment.

## Fixed observations

The diagnostic suite wrapper observes room API requests, response statuses
(including successes), transport failures and HTTP errors, with monotonic time,
current case and browser-context identity/origin. It does not select tests,
change waits, assertions or verdicts. No bodies, credentials, headers or query
strings are captured. The stored event tail is bounded: missing events never
prove that a request did not happen. A diagnostic hypothesis cannot install
additional instrumentation.

## Execution and interpretation

1. Preserve the current frozen tests and exact implementation snapshot. Run the
   complete suite through the diagnostic wrapper, not an edited test workspace.
2. Correlate the second room's join POST, its response, subsequent room polling
   and the first failed assertion in the same browser context. Distinguish
   browser contexts retained from previous cases.
3. No successful join response is inconclusive if the trace is truncated. A
   transport failure points to transport; a 4xx response points to rejection;
   a successful join followed by successful polling shifts investigation toward
   response semantics or rendering. None alone proves the final cause.
4. Attribute each 409 to its path, case and context. Separate deliberate API
   negative probes from normal UI actions and the post-suite preview. Never add
   a blanket 409 allowance or disable console observation.
5. If successful HTTP responses remain insufficient, stop repeating the same
   experiment. Define a separately bounded state observation with no nicknames,
   cookies or private cards before another run.
6. After correction, run the full suite repeatedly on the same snapshot and
   preserve every outcome, including intermittent failures. Diagnostics do not
   approve a delivery or silently amend a frozen test.

## Required independent verification

The repaired after-hand-end case must reach a completed hand while the player
still holds a legal card. A product-only negative control must disable the
ended-hand protection while retaining ownership validation; that case must then
fail. Disabling unrelated rules or replaying an already-used card is insufficient.
Independent review, immutable freeze, full Green, required controls, PR/CI and
post-deploy QA remain mandatory. No negative-control completion is claimed here.

## Installation boundary

Validate offline, then install during a drained maintenance window with preserved
state. Do not clear provider-pause markers, reset budgets, alter active cards or
start model calls as part of this preparation. Keep source and publication checks
separate from claims about the product investigation outcome.
