# Quality lifecycle v2

Status: owner-approved design; policy, offline sensitivity executor, persistent
operator enrollment, legacy admission fences, standalone full-suite Red observer
and durable controller Red ingestion/snapshot producer implemented in source.
The observer and dedicated snapshot copier also passed synthetic Docker
isolation/integrity checks. The v2 chain is not installed, enrolled or enabled in the
running controller. Historical runs retain v1.

## Required order

```mermaid
flowchart LR
    A[Closed tests-only author and native completion] --> Q[Durable fair reconciliation]
    Q --> T[Immutable tests-only snapshot]
    T --> R[Actual full-suite Red]
    R --> V[Independent read-only test review]
    V --> F[Frozen test hashes and criterion witnesses]
    F --> I[Implementation and full-suite Green]
    I --> S[Same-Green positive and negative controls]
    S --> C[Independent immutable delivery review]
    C --> P[PR and CI on exact SHA]
    P --> H[Deploy and QA on exact SHA]
```

There is no independent positive implementation prerequisite before Red. A Red
is not a compilation error, missing dependency, infrastructure failure, setup
failure, skipped test or failure of a pre-existing baseline test. New tests must
execute assertions in their bodies and fail against the pre-implementation
snapshot. Independent review still judges whether those assertions express the
approved behavior; a failing assertion alone cannot prove this.

The test-review approval freezes the whole plan, the exact Red, its snapshot,
baseline and new-test hashes, acceptance IDs and their test-method witnesses.
It authorizes implementation only, not editing tests or approving delivery.
Green must retain those hashes and execute the full suite without selection,
skips, errors or reduced test count. Old approvals cannot apply to a new plan,
run, snapshot or contract.

## Sensitivity, after Green and before merge

- The positive is the actual Green implementation, not a model-authored oracle.
  A Path fixture used to load it must be byte-identical to its Green source.
- A negative changes only declared product-code/data paths in an isolated copy.
  It cannot change tests, the harness, discovery, mocks or CI configuration.
- Every negative reexecutes the complete frozen test inventory. The older
  single-selected-test calibration receipts are not v2 sensitivity evidence.
- Each claimed acceptance ID must have a frozen witness test that actually
  fails with an assertion in the test body. Setup/import errors, survivors,
  missing tests or changes to tests retain the technical hold.
- All required acceptance IDs must be covered. This mechanical coverage does
  not prove business correctness: an independent reviewer must also judge the
  mapping and mutation semantics. Sensitivity cannot replace delivery review.
- Positive, mutations, approval and subsequent publication must bind to the
  same Green snapshot and commit. A later change invalidates the proof.
- The sandbox has no network, credentials, host filesystem, or Docker socket.
  Snapshot and controls are read-only; scratch space is separate and bounded.

## Implemented source boundary

`broker/quality_lifecycle_v2.py` validates the plan, ordered evidence and semantic
facts. Its inputs are not self-authenticating. Its returned receipt explicitly
has `merge_authorized=false` and `delivery_approval=false`.

`post_green_sensitivity.py` reuses the existing multi-Path test loader, but
requires a distinct `post_green_sensitivity_policy_v2` input. It does not accept,
upgrade or emit a legacy calibration approval. It executes the complete declared
inventory for each negative and compares the positive fixtures to Green bytes.

These modules must not be exposed as worker authorization endpoints. A controller
adapter must authenticate native identities, independent decisions, complete
reads, fixed-job isolation, immutable manifests and actual execution receipts
before persisting a qualified transition. Caller-supplied booleans are not proof.

### Persistent source-to-review reconciliation (source only)

`broker/quality_progress.py` is wired into the opt-in watchdog before legacy
reconciliation. It discovers only consumed, closed `tests_only_v2` bindings;
native completion may lag a lease close and is observed without creating another
author. Per-source identity/state and the discovery fairness cursor survive
restarts. Each tick handles at most two sources in least-recently-observed order.
A rejected source cannot occupy the front of every tick. Pending snapshot/Red
jobs retain their original identity; two identical external/discovery failures
produce a visible technical hold for the Tech Lead, not another execution or a
CEO question. Failure messages/private data are not copied into diagnostic prose.

A private OS lock prevents concurrent reconciliations without guessing that an
old timestamp means a process died. Slow operations hold neither the global
admission lock nor a SQLite writer. Maintenance and default-off v2 prevent new
effects. A crash between a completed capture and packet persistence resumes by
reading that exact durable capture, not rerunning its suite.

The review-ready packet binds plan, Red, snapshot manifest, author, reviewer,
candidate test hashes and capture digests. It is produced only from authenticated
controller capture rows, never the worker's returned report. It does **not**
freeze/approve tests, start a reviewer, authorize Green or grant delivery. The
independent read-only review admission/attestation adapter remains to implement
and qualify. This hook is not installed or enabled in the live controller; its
database/native-fixture tests are not proof of autonomous native delivery.

### Actual Red observation, without a positive prerequisite

`quality_red_observation.py` verifies the immutable base manifest, complete portable
contract, original product/protected bytes, baseline hashes and frozen snapshot.
The initial adapter executes Python unittest discovery over the complete pinned
test root. Static class/method inventory is compared with actual discovery;
`load_tests` selection hooks, undiscovered files/methods, skips, expected failures,
import errors, baseline regressions and setup/teardown/cleanup assertions cannot
become Red. Each accepted failure must have an actual traceback frame in the new
test method. An assertion in a body cannot hide a second teardown failure.

No positive fixture or implementation is supplied. Output is captured as a digest;
test/product data and assertion messages are not emitted as diagnostic prose.
The result contains `observed_red_v2` facts, not a controller grant, authenticated
native review, implementation approval or delivery approval. Unsupported runners
are rejected rather than silently substituted. Other runner adapters remain work
to qualify, not a claim of universal framework support.

`Dockerfile.quality-red-observer` builds this fixed entrypoint on a pinned Python
base without package downloads. `qualify_quality_red_observer.py` runs synthetic
Red, all-Green, setup-assertion and snapshot-write controls, baking inputs into
disposable test images. Jobs use a read-only root, no network, mounts, credentials
or Docker socket, an unprivileged user and bounded CPU/memory/PIDs. They are
grouped under the instance's `-tests` Compose project and synchronously retired
with `--rm`. Private contexts, commands, build logs and results are retained for
inspection; obsolete image retirement still follows the separate scoped policy.
The write-negative attempts chmod before writing, so a file's initial mode alone
cannot satisfy the check; each negative must fail for its expected category.
Delayed Docker removal is observed by the same exact name without repeating a
run/delete. An unsettled earlier probe blocks a new qualification invocation.

These Docker checks qualify only the observer on synthetic inputs, not a native
author task. Live fixed jobs can bind the same bounded metadata through the
`QUALITY_RED_INPUT_JSON` environment field in their immutable job identity. This
avoids an extra writable policy volume; the field cannot contain a command or
additional input keys. The observer's pinned image must resolve to the portable
contract's exact test image. Environment-input Docker qualification runs without
a policy file, so a file fallback cannot accidentally satisfy that check.

### Durable controller Red ingestion

`broker/quality_red_capture.py` has no worker endpoint and accepts a source task
identity, not a caller-supplied test report. It authenticates the completed native
author against the enrolled run, workspace/runtime and independent roles. The
source capability must be consumed, closed and the latest attempt for that task;
its controller-owned `quality_native_scopes` record must bind `tests_only_v2`, the
same request/task/run and plan hash. Agent prose never establishes a phase.

The copy receipt must already be complete in the controller's durable copy-job
table, with the exact fixed copy image/command, pinned base, source scope,
destination volume, immutable mounts, prepared test hashes and output digest.
Both `QUALITY_COPY_IMAGE` and `QUALITY_RED_IMAGE` are explicit immutable controller
configuration, never worker input or an automatic fallback to a legacy image.
Inherited image volumes and credential-bearing environment keys are refused;
the configured technical escalation actor must be an enrolled planning role.
The observer job is built from those records, not agent-selected commands. Its
actual identity, complete result, container ID, output hash and job-contract hash
are rechecked against the durable validation-job table before any transition.
The new code deliberately does not reconstruct/upgrade a historical Red or
calibration receipt.

Only after those checks can the capture enter `awaiting_independent_test_review`,
owned by the enrolled reviewer. It still grants no execution, approval or merge.
Context/state digests protect readback against accidental corruption. The durable
receipt can be read after mutable source records are retired, without rerunning
the job. A newly admitted author task can produce a separate Red revision without
overwriting an earlier capture for the same issue. This does not admit another
task, reset a budget or authorize re-observation with changed parameters: phase
admission and any changed-condition recovery remain separate controller decisions.
A per-source private OS lock serializes observers across processes and
is released on process exit. Slow native/Docker operations do not hold the global
admission lock or SQLite writer. Pending observation retains the exact same job;
rejected provenance or an executed invalid Red records a technical impediment for
the configured Tech Lead, preserving evidence and refusing an identical retry.

The tests for ingestion use isolated controller databases and mocked native/copy
provenance; they are not native qualification. The installed admission adapter
still does not mint `tests_only_v2` capabilities, the fixed copy producer is not
wired to a new v2 coordinator, and independent review dispatch/attestation remain
to implement and qualify. Do not populate scope/proof tables manually to bypass
these missing stages or enable v2 based on observer/ingestion tests alone.

### Durable fixed snapshot production

`broker/quality_red_snapshot.py` shares the ingestion source authentication and
per-task OS lock. It persists the exact volume identity and creation intent
before any Docker effect, then delegates to the durable fixed copy-job journal.
An unknown create acknowledgment is observed using the same name, never retried
as another POST. Existing unregistered volumes are not adopted; changed labels,
creation identity, scope or source evidence fail closed. Completed snapshots
retain a hash-bound receipt without authorizing Red, implementation or delivery.
The `advance` entrypoint connects this producer to ingestion but is not a worker
endpoint or native admission adapter. Its controller provenance tests use mocks,
not live native authority.

`Dockerfile.quality-red-copy` has no inherited volumes or credentials and prepares
the snapshot directory for user 10000. `qualify_quality_snapshot.py` exercises the
actual image and named-volume copy-up with synthetic inputs: genuine copy,
duplicate destination rejection, and pre-Red product modification rejection.
Each case reads back the same manifest and unprivileged ownership. Jobs are
networkless, bounded, read-only except the explicitly owned destination volume,
grouped under `-tests`, and retired with `--rm`. The small proof volume and private
intents/results remain preserved for recovery; no volume pruning is performed.
These checks are not a native task, test review, or delivery qualification.

Fixed validation jobs now exclude only proven sealed operator-maintenance
intervals from their observation budget, like the existing copy jobs. Sealed
maintenance prevents new effects; release resumes the same immutable job and
original deadline. Draining or ordinary inactivity does not extend the budget,
and neither a pause nor a restart resets attempts or grants an approval.

### Immutable enrollment and legacy fences

`broker/quality_author_admission.py` implements the source-only first-author
admission adapter. It authenticates a running native task belonging to the
enrolled author, workspace/runtime, sole first issue execution and frozen base.
Maintenance and capacity are checked in the transaction that atomically records
the capability digest, native binding, `tests_only_v2` phase and hash-bound
admission context. There are at most two active/reserved slots and one per author;
a consumed capability without an observable lease does not silently free a slot.
The workspace scope includes this exact task, not a previous issue session.

Its worker selection permits only declared new-test files, no baseline/product
edits, test commands, generic terminal or legacy positive calibration. Tests feed
this selection into the actual ACP permission handler and verify its denial of
product/baseline edits and shell execution. This does not prove installed handler
or filesystem isolation: worker-image selection, workspace seeding/lockdown,
launch-time reauthentication and transport integration still must be wired and
qualified together. The installed legacy launch fence is unchanged.

No retry is minted for a duplicate call or a lost capability response. Only the
capability digest is stored; metadata readback is not a new secret or launch.
Any interrupted admission remains inspectable by request/task/run and requires
evidence-based recovery, not another identical attempt. Transaction failure rolls
back every authority row. These tests use synthetic native fixtures, not a live
agent run. No admission module is exposed as a worker endpoint or enabled merely
because its unit tests pass.

`broker/quality_author_worker.py` prepares a freshly admitted tests-only workspace
through two fixed durable validation jobs: nonroot seed, then controller-only
root lockdown with only CHOWN/DAC_OVERRIDE. It does not call route-dependent
legacy selectors. The exact new-test list, immutable prep image and base manifest
are controller-owned. The dedicated prep image has no inherited volumes, network
credentials or host access. Helpers have no Docker socket; only the workspace
destination is writable, and the base is mounted read-only.

The workspace journal records volume creation intent before effects and retains
the exact creation identity. Unknown acknowledgments are observed without
another POST; unregistered or recreated volumes cannot be adopted. Seed/lock
results must match complete durable fixed-job identity, container and output
hashes, not a worker success claim. Maintenance, expired/consumed capability or
changed native runtime prevents new preparation. Completed readback does not
rerun jobs and explicitly grants neither launch nor delivery; the later launch
adapter must reauthenticate the current task/capability and actual workspace.

`Dockerfile.quality-author-prep` and `qualify_quality_author_workspace.py` exercise
these seed/lock commands with baked synthetic inputs, using named proof volumes
instead of host mounts. A nonprivileged Docker probe can write the selected new
test but cannot write product/baseline files, chmod, unlink, rename, create an
undeclared file/symlink, or bypass the fence with a child process. Protected
hashes remain unchanged. Helpers use grouped `--rm` jobs; the two small proof
volumes and private intents/results remain for recovery. This is real filesystem
isolation evidence, not live Hermes tool-handler, native launch, independent
test-review or release qualification. The current server/worker-image launch
integration and remaining chain are still disabled pending those gates.

`quality_phase_tools.py` enforces `tests_only_v2` at registry dispatch and direct
registered handlers via `review_tool_policy`. Only exact declared reads and a
bounded full-file write to a new test delegate to the existing file handler.
Product/baseline writes, arbitrary patches, terminal/Python/delegation/admin
tools, path traversal and unknown arguments are denied. The original syntax
guard and kernel filesystem permissions still apply. Malformed or conflicting
phase configuration never falls back to the broader implementation policy.

The ACP transport accepts this configuration only for a nonpersistent
implementation session, the exact execution UUID and identical ACP editables,
with no legacy feedback, review-suite or command capabilities. It validates these
conditions before Docker exec, then supplies the same controller-owned config to
the worker handlers. `quality_author_admission.tool_config` derives it from the
persisted plan, not a model argument. The launcher must still select and validate
the immutable qualified worker image and connect this transport to its admission.

`Dockerfile.quality-author-worker` reuses a local already-flattened Hermes runtime
without inherited anonymous volumes or another multi-gigabyte filesystem copy.
It is a qualification build, not a portable distribution or installed deployment.
The workspace qualifier's optional `--worker-image` runs the real Hermes registry
and a direct registered handler with network disabled, no credentials/socket and
no model request. It proves legitimate reads/new-test writes and denied shell,
Python, product/baseline writes and out-of-scope reads. An initial canary supplied
invalid Python text and was correctly rejected by the syntax guard; its failed
receipt remains preserved. A new image with valid synthetic test bytes passed.
`--observe-failure` can close a qualification only from an actual nonzero process
result and retired exact helpers; an unknown/missing result remains unresolved.
Neither these proofs nor a successful metadata readback authorize native launch,
test review, implementation continuation or homologation.

### Opt-in native launch integration (source only)

`broker/quality_author_launch.py` is wired into native admission, asynchronous
startup, exact task-scope checks, transport opening and controller prompt
construction. `BROKER_QUALITY_V2_ENABLED` defaults off; worker/prep/copy/observer
images and the technical escalation identity are explicit operator settings.
The installed controller remains unchanged and sealed pending qualification.

The first capability is consumed only after durable workspace seed/lock and
reauthentication of the current running native author. The worker must use the
configured immutable dedicated image, with no inherited volumes/credential env,
only the owned workspace mount, a read-only root and the owned internal model
network. No legacy route, seed, calibration, editable list or session is selected.
The same transaction records consumption, lease and immutable Docker payload.
Create/start intent precedes its sole POST; lost acknowledgments are observed by
the existing startup journal, not treated as permission for another worker.

The launch path requires asynchronous startup, not a second synchronous execution
route. Pending fixed preparation jobs are observed under the original startup
budget. A persisted phase authorizes the exact task scope; agent notes cannot
override it. Startup and session checks reauthenticate that phase against native
ownership/status rather than confusing the fresh task scope with the generic
issue session scope. Controller prompts replace agent-supplied prompt text with
the tests-only instructions and registered acceptance/test mapping, treating
issue description as requirements data, not tool/approval authority.
The authenticated native issue title/description and a bounded context capsule
are frozen in the admission context before minting the capability. Prompt
construction requires the current issue to match those exact fields and uses
that persisted capsule for the transport's trusted controller envelope. It never
manufactures a larger-prompt exception from current agent text or silently
updates scope after admission. Missing/oversized context rejects admission
without partial authority; changed issue text requires explicit technical
replanning, not a hidden refresh of the authorized test objective.

Transport opening requires the current capability, running lease, exact original
worker payload and matching durable inspection of that container/image/policy.
An opening intent precedes Docker exec; a lost/failed opening cannot silently
recreate a transport. The real ACP transport receives the same execution-bound
handler policy and new-test editables. It grants no test-review, implementation,
merge or delivery approval. The v2 hooks are disabled for legacy tasks; regression
reconstructs the exact earlier pinned server bytes after removing only those
hooks and the explicit phase-specific correction exclusion. Historical pins and
holds remain valid without being converted into new evidence.

These launch tests use actual controller/startup entrypoints with isolated DBs
and mocked native/Docker observations. They are not proof of native agents,
installed startup, paid model execution, independent review or end-to-end delivery.
Qualify the new launch path and remaining review/Green/sensitivity chain before
enabling it for any product work.

### Real Docker/ACP qualification with synthetic native authority

`qualify_quality_author_launch.py` and `tests/quality_launch_docker_probe.py`
exercise the candidate controller's actual admission, asynchronous startup,
workspace seed/lock, worker launch, single transport, ACP `initialize` and
`session/new` paths against real Docker and Hermes. Native records/roles are
explicit fixtures in a separate private SQLite DB; no Multica issue is created,
no candidate HTTP server starts, and the installed controller's DB/maintenance
is not replaced or released. This is not a native-agent or delivery qualification.

The harness reuses an exec process in the already-authorized controller, rather
than mounting the Docker socket in another container. The candidate source is
copied into a unique private tmpfs directory, hash-checked before import and run
only against that isolated state. Transfer/export use tar streams through exec:
Docker Desktop's archive API cannot reliably address the same tmpfs directory.
No installed source file is overwritten. The model proxy must already be stopped;
only initialize/session-new frames are sent, never session/prompt or a model call.

Private source/input manifests, intents, DB, protocol response digests and logs
remain archived. After the actual process terminates successfully, exact owned
workers/helpers are archived, stopped if necessary and removed without force or
volume deletion. IDs come from `docker ps --no-trunc`; short/full-ID comparisons
must not be treated as ownership evidence. Unknown stop/delete outcomes are
observed, never repeated. `--finish-retirement` cannot rerun the candidate or
mint a grant. `--resume-before-execution` requires no process intent/state and
continues the original allocation/base; it cannot restart a candidate execution.
Any unfinished operation fences a fresh run until its actual effects are settled.

The reference proof passed with one native-fixture capability, two complete fixed
preparation jobs, one worker, one transport and two successful real ACP events.
Its three containers were retired; proof volumes and evidence were retained.
The installed controller stayed sealed with no native workers, and no model
prompt was sent. Native-agent execution, snapshot/Red handoff, independent test
review, Green, sensitivity, PR/CI and same-SHA deployment/QA still require their
new-chain integration and end-to-end qualification.

`broker/quality_lifecycle_enrollment.py` binds a new run and previously unexecuted
native issue to the complete portable contract, repository, registered base SHA,
base-volume manifest, native workspace/runtime and independent author/reviewer.
Its contract digest is the canonical compact JSON digest used by the v2 policy;
it is not silently substituted for any legacy digest format.

Enrollment requires the exact sealed/drained maintenance operation, no active
native tasks/leases/controller cycles and no outstanding execution capabilities.
Any prior native run, delivery route, handoff, contract revision or scope-recovery
record rejects conversion. A new plan cannot overwrite an existing issue/run.
SQLite serializes short admission transactions; slow native and Docker evidence
reads happen outside the admission lock and writer transaction. Durable authority
and base metadata are checked again before the final atomic insert. A timeout
persists no enrollment; a restart or duplicate request reads the same committed
record without creating a second run or replaying an external operation.

The initial state is **`enrolled_pending_adapter`**, not runnable or approved.
The baseline hashes are expectations bound to the frozen base; enrollment does
not claim that a runner already verified those bytes. No task, wakeup, tool grant,
model call, delivery approval or legacy-evidence conversion is produced.

The source admission checks in `native_grant`, `execute_grant` and legacy route
registration refuse enrolled v2 issues. In particular, a capability minted before
enrollment is checked again at launch. Legacy issues continue unchanged. These
checks are exercised through the actual Python entrypoints with isolated test
databases, not treated as installed/native end-to-end evidence.

There is deliberately no worker HTTP registration endpoint and no global v2
switch. Do not copy only the enrollment module into the installed controller:
the matching admission fences and remaining execution chain must be qualified
and installed together before any new v2 work is enabled.

## Installation gates still required

1. Qualify and install the source enrollment and legacy fences before any
   task/grant in a fresh run. Bind repository, base, contract and role identities;
   reject reuse of a legacy blocked issue.
2. Capture genuine Red without calling the old positive calibration prerequisite;
   reauthenticate its runner receipt before independent test review and freezing.
3. Bind the existing author continuation and immutable delivery to the new plan.
4. Let the technical team propose negatives against the actual Green snapshot;
   execute them through a durable fixed sandbox job and review their semantics.
5. Require the same qualified sensitivity proof at publication, immediately
   before merge and deployment; missing or stale proof must fail closed.
6. Verify crash recovery between every durable intent and external effect;
   do not reset author budgets or replay uncertain Docker/native operations.
7. Run a new end-to-end native qualification, including a surviving negative,
   rejected test edit, stale approval, correction and eventual homologation.

No existing hold, policy or historical receipt is rewritten by adopting v2.
There is no global switch that silently converts old routes. Legacy gates remain
installed until the new chain is complete and explicitly qualified. Source tests
or a synthetic probe alone never qualify the autonomous team.
