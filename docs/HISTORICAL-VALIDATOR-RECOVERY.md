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
