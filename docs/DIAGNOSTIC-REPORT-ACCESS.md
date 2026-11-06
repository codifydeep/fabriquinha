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

## Explicit strengthening of a scoped test

`technical-test-repair-1` remains a setup/action repair with unchanged assertions.
A CTO can instead select `mode: strengthen` with exact existing cases, paths and
`product_imports`. The controller records `technical-test-strengthening-1`; an
old authorization is never converted into this permission.

Strengthening appends direct unittest assertions after every unchanged existing
statement. It permits authorized local imports of existing root product modules
and fresh local literal/product-call assignments. It forbids changing old
statements, helpers, discovery, neighboring cases, early exits, rebinding and
production code. This deliberately small syntax does not include loops or
`subTest` blocks. Independent semantic review remains required: structural
preservation alone cannot establish meaningful coverage.

An unchanged candidate is rejected explicitly, separately from changes outside
the allowed paths. A failed strict test author can receive one new strengthening
authority linked to the exact parent repair, incident, current experiment and
freeze. The new graph preserves the old attempt and the original implementation
snapshot. It requires fresh Red, independent freeze, Green, effective controls
and independent delivery review. Repeating a failed strengthening authority is
not implicitly authorized.

Offline qualification is available through `qualify_test_strengthening.py`
(real isolated Docker tests and controls with programmed roles) and
`qualify_strengthening_native.py` (native Kanban successor/restart with programmed
suite reports). Neither script establishes autonomous model reasoning or product
homologation.

## Preserved implementation during test repair

A test-author workspace is the Red baseline and may intentionally lack the
implementation being repaired. When the current repair authority retains an
implementation snapshot, diagnostic context lists its bounded root Python files.
Use `diagnostic_report` with `implementation_path` and `offset: 0` to read it;
follow `next_offset` for subsequent pages. Do not combine this with `experiment`.
The controller resolves the snapshot from the validated repair authority, checks
the immutable file hash and limits each page. The caller cannot choose a snapshot
or host path. Reading code never selects a fresh experiment or authorizes delivery.

## Review holds and author failures

A settled review escalation may be in native `blocked` or `triage`. The CTO
follow-up requires the exact latest ended run, contract, unchanged snapshot,
current experiment and settled controller effects. Its existing idempotency key
prevents duplicate follow-ups after restart. This does not approve tests or
reopen implementation automatically.

Review incidents do not enter the test-author syntax-repair lane. A coverage gap
outside a maintenance authorization remains an independent review finding; the
CTO must supply an executable, scoped technical decision. Existing assertions,
case inventory and release quality gates remain protected.

A repeated CTO hold for the same immutable incident reuses the original decision
activity after validating its incident, role, release and payload. Its recorded
diagnosis is never overwritten. A hold without a current experiment remains a
technical impediment with an explicit missing-evidence reason; it cannot become
authorization by attempting to load a null receipt.

Coverage expansion beyond an existing maintenance scope requires the explicit
cumulative authorization below. Such a successor protects both the original
freeze and the complete current candidate, including previously added checks.
A textual technical ruling alone does not widen the test-writing tools.

## Cumulative coverage authorization

A settled independent review of an explicitly strengthened test candidate may
request `repair_tests` from the CTO. The authorization retains the exact parent
repair, original freeze and current candidate. It allows only additive checks in
named existing cases using authorized product modules. Helpers, browser observers,
discovery, case inventory and existing statements remain protected.

The controller validates the current candidate against its parent authority and
checks the successor against both the original freeze and that candidate. This
prevents removing checks added since the old freeze. The QA workspace starts
from the current candidate; implementation still uses the preserved product
only after a new independent freeze. Red, Green, relevant negative controls and
delivery review remain required. A repeated unchanged submission is rejected.

The programmed native strengthening qualification includes rejected coverage,
CTO authorization, an idempotent successor, cumulative QA submission and an
independent freeze. Its reports are programmed; it does not qualify autonomous
reasoning or replace real executor and end-to-end delivery evidence.

Suite rejection messages prioritize a bounded QA failure summary before other
error categories. They include the test count and referenced job, not the full
case inventory. This prevents tool-output truncation from hiding the assertion
that failed. The immutable job retains the complete report; truncation of the
message never changes validation outcomes or grants delivery credit.

## Resuming local negative controls

For browser TDD, the model submits its complete ordered mutation set once.
The controller seals the Green receipt, original native run, freeze, project,
product snapshot and mutant snapshots in a private submission receipt. Hermes
schedules the implementation card and resumes the same author in bounded local
validation steps. Each step revalidates saved job evidence and starts at most one
additional control. The complete receipt and reviewed test-author exclusion are
required before requesting independent implementation review. A missing target,
surviving mutant, changed workspace, different freeze or foreign claim blocks
that transition.

An assisted migration of a pre-existing timeout requires its exact author tool
call and matching Green, snapshot, current native card and ordered mutants.
Runs with identical code still have distinct evidence identities. The native
offline proof uses programmed suite results and real scheduling and review claims.

A resumed batch still collects its remaining ordered controls after a mutant
survives a complete valid suite. The final refusal records every surviving
mutant and the missing targets. A survivor alone vetoes review even when other
mutations witness all mandatory cases. Infrastructure errors and incomplete
suite membership stop observation. Recovery checks the active claim and the
sealed submission before reading a refusal under its original Green identity.

An authenticated rejection probe can be offered for a single existing case after
a rejected additive repair. The offer binds the source incident, parent repair,
freeze and offline experiment. The fixed operation uses two existing browser
contexts, the local target, a fixed route, a bounded JSON payload and redirects
disabled. Acceptance requires the rejected POST to return 409 and both contexts
to observe their previous state. The entire suffix is compared structurally and
all preceding statements and other methods remain protected. The CTO must issue
a fresh scoped repair decision before the author receives the template. The
candidate still requires Red and independent review.

Queued implementation submissions pair each mutation with a map of frozen case
IDs to the behavior it violates and the assertion expected to catch it. The
controller checks the complete map before starting Green. Authors can submit up
to 16 independent mutations, so a package with 11 cases can exercise each case
separately. The sealed submission retains the map across worker restarts.
Only the observed suite results count toward coverage.

When a sealed mutant raises a runtime error, its suite receipt identifies the
implementation author, Green and freeze for diagnosis. The author must correct
the mutant. A transport exception converted into a test assertion cannot
demonstrate which user-visible behavior changed. Existing native triage limits
still apply to resuming a failed author.

When an invalid sealed mutation has already led to a fixture repair, the CTO
can choose `return_controls` after a fresh experiment on the triaged fixture.
This applies only while the fixture workspace matches its independently
reviewed snapshot. The controller restores the exact native tests card and
creates a Backend successor from the corresponding Green implementation. It
publishes the replacement graph before activating workers. The successor must
produce fresh Green, controls and independent implementation review.

If the implementation itself reaches native triage after a sealed mutation
produces a runtime error, a fresh CTO experiment and `return_controls` can
also create a successor for that same implementation author. The successor
keeps the reviewed tests card and receives the last completed control report
on the exact product and freeze, including edits, survivors and assertion
failures. It must submit a fresh batch. The controller refuses the same
rejected mutant on unchanged source and limits this succession to one per
product, freeze and rejected mutation.

For a returned author with a replayable prior batch and the same product and
freeze, `delivery_repair_controls` accepts only replacement product edits for
all surviving indices. The worker supplies the changed controls. The controller
reconstructs the other edits and target mappings from the verified batch and
uses the standard submission path to run fresh Green, all controls, and
independent review. A changed product, changed freeze, repeated survivor, or
missing replacement is refused. The full submission path remains available.

A new scoped strengthening decision can explicitly name a public product
class and its methods via `repair_scope.stateful_api`. The class and methods
must be declared in the preserved source of an authorized product module.
The test author may then construct a fresh local instance, call those methods
and inspect returned data with bounded literal keys or indices. This permits a
reachable sequence of domain operations while preserving every existing
statement in the test. A previous authorization without this field retains its
original grammar. Independent freeze and behavioral controls are mandatory.
