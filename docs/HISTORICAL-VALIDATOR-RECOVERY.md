# Historical validator provenance and integration recovery

An accepted release retains its own validator bundle. Reading that accepted
history must not require the validator currently installed for new work.
Conversely, a historical report must never satisfy a new validation gate.

`AcceptedHistory` is a read-only artifact view selected from a controller-issued
`HOMOLOGADA` receipt, its exact release graph and matching deployed QA job. It
verifies the bundle and preserves commit, project, release and QA bindings. It
cannot capture files, create workspaces or write receipts. Maintenance provenance
uses this view when inspecting the frozen tests of its accepted source. Normal
execution continues using the installed bundle without a historical fallback.

## Scoped assisted recovery

The operator-only `repair-history` operation requires a paused dispatcher, no open
runs or pending source effects, the exact completed CTO hold for the bundle
mismatch, and an already assisted graph. It verifies the retained independent
implementation approval and successfully resolves the accepted rollback before
recording repair authority. The existing native triage transition resumes the
same integration card; no body, test, workspace, counter or delivery is reset.
A durable receipt makes repetition and interrupted recovery idempotent. Another
failure still follows the existing breaker and technical escalation.

The copied-board proof checks nested maintenance provenance, exact rollback,
read-only history, rejection of historical reports by current gates and one
native resume with unchanged counters and delivery. Offline checks do not replace
real PR/CI, rollout and deployed QA. Those remain required after resumption.

The same change fixes stale-sandbox recognition for the optional pinned-browser
mount. Retirement still verifies the original journal identity, native run,
process liveness, container ownership and pinned mount before scoped cleanup.
Unknown shapes and active workers are preserved.

## Cross-release qualification

The existing release qualifier accepts `--acceptance-suite --continuity
--validator-continuity`. It delivers two dependent packages, then a subsequent
release retaining their tests. Between completed releases, and only with a
drained qualification installation, it selects a second validator generation
with a stricter diagnostic-output bound. Historical receipts must remain byte
identical; the old acceptance selects its original read-only bundle while new
QA must use the newly installed bundle. The second rollout must exercise the
exact previous homologated artifact as rollback before restoring its candidate.

This is an isolated compatibility fixture, not a production migration API.
Authors and GitHub transport are programmed; Docker, browser and native lifecycle
are real. No paid model call is made. A passing result does not qualify agent
autonomy, real GitHub CI, or a general production installer. The existing
pre-quality interruption scenario separately tests a half-committed graph/pin
upgrade and idempotent reconciliation without duplicating cards.

Inspect `receipt.json`, `continuity-receipt.json` and
`validator-continuity-receipt.json` in the private qualification root. A receipt
from an intermediate stage alone is insufficient: final chain completion and
scoped retirement must also succeed. Failed or still-running attempts must not
be reported as qualified.

The journal unit checks also terminate a real subprocess immediately after a
filesystem stand-in records an external effect, before acknowledgement. Recovery
must observe the existing effect, preserve its deadline and never resend. This
check does not substitute for the planned interruption during a real deployment.

## Pending-effect supervisor qualification

`scripts/qualify_hermes_integration.py --compose-ack-loss` extends the existing
isolated integration fixture. Its fault injector is refused outside a
qualification project. After the real Compose command returns, the first
acknowledgement is lost and the existing journal retains an uncertain intent.
The driver waits for the native scheduled handoff and settled workers, stops
the supervisor, verifies the unresolved effect and starts the supervisor again.
The resumed worker must reconcile that effect, then finish rollback and browser
QA. Every Compose operation is counted by its durable operation directory; any
resend of that operation fails the proof. PR creation and merge must still occur
only once through the existing simulated GitHub transport.

This mode is prepared but is not qualified until its complete integration receipt
and retirement succeed. It does not exercise production backup restoration, real
GitHub outages or model judgment. It requires a fresh private root and the same
image/upstream arguments as the original integration qualifier. Never enable
its fault marker in an installed product project.

## Qualification result — 31 October 2026

The corrected cross-release attempt completed both releases and all three work
packages. Its final receipts confirm unchanged historical receipts and baseline
tests, QA bound to the new bundle, exact prior-artifact rollback, interrupted
pre-quality upgrade reconciliation and scoped retirement. Paid calls: zero.
The first attempt failed because the fixture redeclared an inherited regression
gate; it remains failed. The corrected generator has an offline preflight using
the same manifests. No product gate was relaxed.

This closes the consolidated deterministic compatibility scenario, not production
migration qualification or repeatability with model-driven agents. The proposed
product delivery and the pending-effect operational proof remain separate work.
