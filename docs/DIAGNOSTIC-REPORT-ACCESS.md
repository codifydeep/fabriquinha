# Diagnostic report access

Large diagnostic results remain in immutable controller receipts. When a result
exceeds the inline bound, `diagnostic_validate` returns its identity and summary.
Use `diagnostic_report` with `offset: 0`, then each returned `next_offset`, until
it is null. Pages contain JSON text fragments; concatenate them to reconstruct
the payload. Host paths and SDK spillover caches are not the report interface.

The reader requires a valid current run and either its experiment or a retained
experiment satisfying the historical scope checks below.
It cannot change the snapshot, authorize test maintenance, approve a delivery or
transfer responsibility. Existing native decision and independent review gates
remain mandatory. Decision validation errors identify required, missing and
unexpected fields so the agent can correct its call without guessing.

A rejected negative control identifies its one-based position in the submitted
set, mutant snapshot, retained suite job, failure count and suite membership
result. A surviving mutation is not evidence of delivery: investigate whether
the scenario reaches the affected behavior before replacing a control or
proposing independently reviewed test maintenance.

Diagnostic event retention reserves up to 128 slots for HTTP/network errors and
server resource observations before filling a 256-event window with recent
traffic. This bounded view is not a complete capture; raw job output remains
archived. Compact results include QA status and up to four error events so
routine polling cannot hide the reason for failure behind report pagination.

Historical lookup accepts an explicit `experiment` receipt with `offset`.
A prior run is readable only when its diagnostic kind, release, incident and
source snapshot match the current diagnostic. Reading never selects that
experiment as a fresh decision authorization. Cross-incident access is rejected.

## Exact citations and context versioning

A finding may use `evidence: "incident"`, `evidence: "experiment"` for the current
experiment, or the exact retained receipt returned by `diagnostic_report`.
The controller revalidates the receipt on each decision, including after activity
reconstruction. A historical citation never populates the current experiment;
resume and test repair still require their existing current-experiment gates.

A held decision may have no new experiment. Its continuation preserves that
absence as `observations: null`, retaining the prior decision and its citations
without inventing validation. It can proceed with diagnosis; author resumption
still requires a fresh experiment. Malformed non-null receipt IDs remain errors.

Diagnostic session anchors include a tool-contract version. Changing that
version preserves old transcripts but starts a fresh diagnostic context. Retries
under the same version retain their anchor; this is not authorization to replay
completed external effects.

## Offline evidence and limits

The `qualify_hermes_recovery.py --historical-citation` scenario passed against the
pinned Hermes using native SDK tools, Kanban and disposable Docker jobs with
programmed loopback responses. Nine runs covered prior-report citation, refusal
of historical-only resume, a current CTO experiment, author resumption, changes
requested by an independent reviewer, corrected submission, review, and service
restart without duplicated recovery actions. No paid model was called.

This proves the baseline recovery protocol, not LLM reasoning or product
homologation. The executable-decision variant also passed a dedicated native fixture with
real Docker observations: historical-only resume was refused, the current CTO
experiment allowed a structured ruling, and reconstruction applied exactly one
author resume. This second proof uses a programmed initial decision context and
does not claim autonomous incident classification. Provider admission is now checked before native claim through a scoped adapter
at the pinned Hermes respawn-guard seam. The original guard runs first; another
connection is unaffected; restoration occurs on success or exception. No upstream
file is changed. This compatibility seam must be requalified on Hermes upgrades.

`qualify_provider_admission.py` used real native dispatch with a programmed spawn
callback: repeated provider unavailability created no model task runs, fixed
integration remained eligible, and availability admitted the model task once.
This is an admission proof, not execution of a real deployment. The final
combined recovery scenario passed again with context versioning and
provider admission connected: nine native runs, independent change request and
review, real Docker validation and supervisor restart without duplicate recovery.
The full offline suite passed 587 tests. Source changes do not
raise the provider quota or release its operational pause.
