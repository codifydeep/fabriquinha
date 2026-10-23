# Quality lifecycle v2

Status: owner-approved design; policy, offline sensitivity executor, persistent
operator enrollment, legacy admission fences, standalone full-suite Red observer
and durable controller Red ingestion/snapshot producer implemented in source.
The observer and dedicated snapshot copier also passed synthetic Docker
isolation/integrity checks. The v2 controller source is installed in preview
in exclusive qualification mode. Activation was checked while sealed, then the
barrier was released and one fresh issue assigned. A real native author task
and worker were observed running; the v2 chain is not yet qualified end to end.
Historical runs retain v1 and their coordinators remain inactive in this mode.
The source coordinator now also reaches durable local Git binding, full-suite
Green and the first post-Green reversion control. These paths are enabled only
for the controlled qualification. Reversion passed a synthetic Docker qualification;
native end-to-end execution, additional-control recovery and later gates remain
unqualified.

## Mixed Python/Node baseline boundary

The actual disposable repository runs both full Python and Node suites in CI.
Its Python browser-VM regressions also require Node. The Python/Node runners and
controller validators are installed and enabled for the enrolled qualification; no
pre-existing regression is omitted. The standalone `quality_node_baseline.py`
diagnostic alone still does not count as native gate evidence.
Full discovery uses a fixed reporter, verifies test files/hashes, rejects
partial inventories, skips/todos/failures and removes inherited Node options or
credentials. Test stdout is hashed, not accepted as a protocol record.

`qualify_quality_node_baseline.py` diagnoses all tracked regular Git blobs in an
isolated read-only snapshot, with fixed full Python and Node discovery. The real
baseline passed 380 Python and 36 Node tests on Linux without skipping. Its
receipt explicitly grants neither Red, Green, native qualification nor delivery.
The source integration now requires `node_baseline_tests` hashes for every
recognized Node test path in the plan. These paths cannot be reclassified as
editable product or omitted from the frozen map. The full Node observation is
part of Red, Green and negative-control suite facts; each snapshot is bound,
and Green/control preserve exact case membership, runtime version and hashes.
Controller validation also checks the reversion observation against the reviewed
snapshot, not the candidate. A version-1 diagnostic cannot satisfy the required
version-2 Node facts. Pure facts still do not authenticate their own execution.

A real read-only Linux Docker canary passed the source Red → Green → reversion
functions (including fixed Green-job dispatch) with actual Node reexecution,
source hashes and frozen inventory. Source, review and commit identities are
synthetic: this is not an independent agent verdict or native qualification.
The installed controller/runners have been upgraded to these gates, including
dispatcher pin migration without journal/counter resets. Supported mixed mode
is primary Python unittest plus protected baseline Node tests, not arbitrary
Node authoring frameworks. Qualification dispatch is not general release approval.

## Operator enrollment and execution isolation

`prepare_quality_enrollment.py` builds the portable contract and v2 plan from
every tracked regular blob of verified GitHub main with green CI. It freezes
all existing Python and recognized Node tests; new tests are authored only by
the assigned agent. The operator selection binds issue/run, roles, criteria,
allowed product paths and expected test-method witnesses, not implementation.
`enroll_quality_lifecycle.py` checks the private payload hash, pinned controller
incarnation and exact sealed maintenance identity before the fixed enrollment
operation. `--observe` only reads back that same immutable request; a timeout is
not successful enrollment or permission for a replacement issue.
The enrollment preflight also resolves the contract's `test_image` inside the
pinned controller and requires that exact configured `QUALITY_RED_IMAGE`, its
observer entrypoint, unprivileged user and safe metadata. A bare Python/Node
base is not the Red observer, even if it can execute the test suite. This check
must happen before any native author run. New enrollments are allowed under
sealed maintenance in either disabled mode or fully enabled exclusive mode;
partially enabled or mixed legacy/v2 mode is rejected. Historical blocked
enrollments remain immutable: correcting their contract requires a fresh run,
not editing their receipt or replaying their author capability.

The new source isolation mode `BROKER_QUALITY_EXCLUSIVE_ENABLED=1` prevents
legacy grants, rejects unenrolled native issues and chooses only the v2
coordinators. All four v2 phase flags are separately required. Legacy journals
remain preserved, not completed or reset. The isolation code is tested and
installed and activated for the controlled native qualification. Leaving
maintenance in a mixed legacy/v2 coordinator mode is not the qualification path.

`activate_quality_runtime.py` performs a separate operator transition using
`compose.quality-v2-exclusive.yaml`. It requires the same installed image, a
verified restore backup, one unexecuted enrollment, no active leases and the
host scheduler disabled/unloaded. Only the four phase flags and exclusive-mode
flag change. Credentials, image selectors, volumes, resources and other
containers remain exact. The durable effect intent prevents repeating `up`
after a lost response; expiry remains a visible DevOps block. Activation keeps
maintenance sealed and neither starts the model proxy nor assigns the issue.
Maintenance release and the first native assignment are distinct operations.
Historical enrollments may coexist with a fresh activation target only when
their authenticated team records remain technically blocked; activation never
clears those incidents. A sealed source upgrade reapplies the OFF overlay last,
even if an earlier exclusive overlay is present, while preserving an existing
exclusive fence. Phase flags are reenabled only by the separate activator.

Tests-only prompts must publish the exact absolute `read_paths` and
`editable_paths` supplied to handlers and ACP permissions. Repository-relative
criterion identifiers are not tool addresses. Relative tool paths remain
forbidden. Authors must read registered product/test files, use an exact
permitted write path and read it back; denial is not successful persistence.
This interface correction is tested in source; existing blocked tasks are not
reopened or treated as successful test authorship.
The absolute-path prompt correction is now installed, with phase flags off,
exclusive isolation retained and maintenance sealed. Native qualification has
not been restarted after this correction yet.
The zero-model Docker/ACP canary explicitly resets its copied broker's team,
exclusive and implementation flags, independently of the installed process.
Its individual author/Red/review adapter must not accidentally enter the team
coordinator. `qualify_quality_author_launch.py --retire-failed <operation>`
requires a terminal failed receipt and retires only stopped owned helpers after
archiving logs/metadata. The experiment stays failed; this cannot approve a
test, replay a model task or delete its volumes. A fresh canary after the flag
isolation fix passed real author/Red/readonly-review transport without prompts
or model calls; its native API authority remains explicitly synthetic.

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
  Reusing the immutable reviewed Red as that isolated product reversion is valid
  only when its frozen tests equal Green, non-product bytes remain unchanged,
  and the complete suite is actually reexecuted after Green. The old Red receipt
  alone is never a post-Green negative execution.
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

`quality_reversion_job.py` is a separate fixed, read-only executor for real
product reversion, including tests which import product modules rather than
Path fixtures. The reviewed product must equal the baseline; differences from
Green must be declared product paths. Criterion coverage is derived from actual
behavioral assertion failures in the complete frozen inventory. Partial coverage
is retained but never qualifies sensitivity.
`broker/quality_sensitivity_capture.py` authenticates Green, exact Git binding,
both volume incarnations and the new fixed validation-job receipt. Complete
coverage reaches independent delivery review only. Missing witnesses become a
CTO-owned incident for additional QA controls; that additional-controls executor
is not implemented yet. Transient observations preserve the original deadline;
expired source outages become visible incidents, not unbounded polling.

These modules must not be exposed as worker authorization endpoints. A controller
adapter must authenticate native identities, independent decisions, complete
reads, fixed-job isolation, immutable manifests and actual execution receipts
before persisting a qualified transition. Caller-supplied booleans are not proof.

### Local candidate authority and preview installation

`quality_candidate_authority.py` uses fixed operator-local Docker-exec verbs
from `broker/quality_candidate_rpc.py`, never a worker or HTTP endpoint. The
installed immutable image, Compose ownership and exact container identity are
checked around every call. `about` remains available while execution is off;
`pending`, `inspect` and conditional/idempotent `record` require v2 implementation enabled
and no maintenance barrier. A lost reply is not proof a process stopped: the
host reads the durable binding before any further export or Git effect.

The fixed `pending` adapter is installed but disabled with the rest of v2. It
paginates only unbound delivery captures, verifies durable capture hashes, and
reports corrupt rows separately rather than preventing discovery of later cards.
`quality_candidate_dispatch.py` owns a private SQLite queue, kernel lock and
restart-stable scheduling tickets. A pass handles at most two cards; existing
export/Git journals own all effect identities. Expiry may observe an already
recorded binding but cannot initiate another export or Git effect. Authority
outages have durable health and escalation deadlines. A real installed-controller
maintenance probe recorded zero effects. The macOS one-shot host service is
installed and scheduled every 15 seconds; independent process runs completed
with exit zero under maintenance. A private hash-pinned configuration and
intent-before-tick journal survive restarts. Two interrupted/unexpected ticks
latch a CTO hold that process reappearance cannot clear. Read-only `--status`
does not probe Docker or run a tick. Registration is separate from launchd
bootstrap and can persist an exact user login plist without replacing different
contents. Logs use the standard private per-user Library/Logs location.
This idle qualification is not recovery of a real pending native card; the native
candidate chain remains unqualified. Image/repository-map changes require a
reviewed migration preserving those journals, not a new empty private directory.

`install_quality_preview.py` installs source only, leaving all v2 flags off.
It requires sealed/drained maintenance, a fresh compressed SQLite backup with
zeroed-scratch restoration proof, private configuration recovery and an intent
before a single scoped Compose replacement. Unknown replacement results are
observed, never replayed. Startup namespace, loopback ports, worker image and
model call ceiling are preserved from installed services, not guessed from
Compose defaults. Live pin files stay outside backup-retirement directories.
Data volumes, models and unrelated containers must remain unchanged. The only
allowed socket source alias is the existing Docker Desktop proxy/native pair,
with unchanged destination/access and a same-daemon check inside the controller;
arbitrary socket paths or volume changes are rejected. No socket is added to a
worker or helper. Preview installation does not release maintenance or qualify
an autonomous delivery.

The optional private `--runtime-config` allows exactly six immutable quality
image selectors and two distinct enrolled planning-role identities (Tech Lead
and CTO). `quality_runtime_configuration.py` checks current controller identity,
sealed/off state, role modes, image IDs, non-root users, fixed entrypoints,
supported phases/operations and absence of inherited volumes or credentials.
Activation flags, model settings, commands, mounts and gate exceptions are not
accepted inputs. The exact selectors bind to the installation operation;
existing credentials, resources and mounts retain their preservation checks.
These selectors are installed in the reference while execution remains off.
Current worker/runner images passed synthetic Docker/ACP and frozen-test/copy
probes; no native task or release was authorized by configuring them.

The backup wrapper accepts a fresh `--backup-id` under the existing sealed
operation, so a new recovery point does not open a dispatch window. The explicit
compressed-size ceiling is checked with scratch/free-space headroom; existing
archives are never overwritten.

### Persistent source-to-review reconciliation (installed, execution disabled)

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
independent native review/read attestation is implemented below but still needs
real-agent qualification.
This hook is installed but not enabled in the live controller; its
database/native-fixture tests are not proof of autonomous native delivery.

### Snapshot-bound independent test-review admission (execution disabled)

`broker/quality_test_review.py` prepares an immutable assignment from the exact
review-ready packet and durable Red capture, reauthenticating the original native
author, source phase, base and enrollment. It requires the author's persisted
admission/context capsule, preserving the original requirements instead of
asking a reviewer to infer intent from test counts or an acceptance ID alone.
Changed issue text is a technical replan, not an implicit scope refresh.

Dispatch uses the existing native independent-review wakeup API. A durable intent
precedes its only possible POST. After a crash or lost response it only observes
the same immutable marker. A maintenance-adjusted deadline bounds an unobserved
dispatch; drift or an unconfirmed outcome produces a preserved technical hold
for the configured CTO, not the CEO or an automatic re-post. The separate
`QUALITY_REVIEW_ENABLED` adapter flag defaults absent/off and must remain off
until the worker launch/attestation chain is implemented and qualified.

Admission checks the exact native task, independent reviewer, wakeup ID, complete
handoff note, workspace/runtime, sole reviewer execution and still-current author
delivery. Grant digest, native binding, `test_review_v2` phase and hash-bound
context commit atomically. Lost capability responses cannot mint a replacement.
The global two-slot/per-agent one-slot rules also apply to review; a consumed
capability without an observable lease cannot silently free capacity.

The handler/ACP contract supports `test_review_v2` explicitly: empty editables,
only registered `/delivery/` paths, explicit read pages of at most 100 lines,
no terminal/patch/write/delegation/admin and no legacy suite capability or
persistent session. Direct handlers and registry dispatch enforce the same fence.
The isolated canary additionally tries raw chmod/write against a read-only mount.
The actual Hermes registry, direct handlers and mount passed this synthetic Docker
qualification, alongside the author seed/lock/write phases. All five helpers
were retired with `--rm`; the tiny proof volumes and private receipts remain.
This is handler/filesystem evidence only, not a native review verdict or
frozen-test approval. No prompt/model request was sent.

### Read-only review worker and shared durable startup (execution disabled)

`broker/quality_review_launch.py` connects review admission to the existing
asynchronous worker/startup/session entrypoints. Its only mount is the exact
controller snapshot at `/delivery`, read-only. The snapshot's persisted volume
creation identity, copied manifest/copy receipt, capture packet, assignment and
admission are revalidated; another volume with the same name is not adopted.
The author workspace is never mounted or seeded. The reviewer has empty
editables/commands, no legacy suite capability and a fresh nonpersistent session.

`quality_worker_runtime.py` shares the one-shot create/start/transport journal
between author and reviewer while keeping phase authority, payload and tools in
separate local adapters. There are at most two workers and one per agent,
including another scope admitted through legacy code. The per-agent invariant is
rechecked atomically at launch, not merely when the capability was reserved.
Unknown create/start acknowledgments use the same actual startup observer;
lost transport-opening outcomes cannot create another session.

`quality_launch_router.py` selects only by durable admission ownership. Native
review admission also requires the persisted wakeup assignment. New source hooks
preserve exact earlier server hashes when removed; legacy requests cannot become
v2 review merely by declaring a mode. Both v2 and review flags default off.
`BROKER_QUALITY_REVIEW_WORKER_IMAGE` and `BROKER_QUALITY_CTO` are explicit operator
configuration, not worker input or automatic fallback values.

`qualify_quality_author_launch.py --review-chain` passed the actual sequence:
fixed operator canary through real author handlers, stopped author worker,
immutable copy, genuine full-suite Red, review assignment/admission, worker launch,
ACP initialize/session-new and real review handler/raw-write negatives. Native
identities, completion and wakeup are explicitly synthetic fixtures in a private
DB. Red/copy/job evidence is generated by the real fixed Docker executors, not
inserted as a fixture report. All six helpers/workers were archived and retired;
proof volumes remain. No candidate HTTP server, model prompt or real native
review verdict is involved, and the installed controller stays unchanged/sealed.

### Complete reads, native verdict and durable test freeze (execution disabled)

`test_first_protocol.prepare_red(include_inventory=True)` optionally emits every
copied file's hash and byte size, bound to the canonical immutable manifest.
`TEST_FIRST_INCLUDE_INVENTORY=1` is fixed controller configuration for v2 copy
jobs. The legacy/default receipt shape is unchanged. Historical receipts without
the inventory are not retroactively converted to full-read/freeze evidence.

`quality_review_reads.py` compares actual numbered handler pages against that
complete manifest. Every registered policy/product/test file must be covered;
partial, clipped, contradictory, duplicated-call, missing or wrong-byte reads
cannot become inspection. Empty files require an actual successful empty read.
Unicode paths and LF/CRLF renderings are accepted only when the reconstructed
byte count/hash matches the snapshot, not by normalizing away a difference.
Unsupported representations remain a technical impediment. The v2 controller
stream preserves these pages independently of UI truncation; there is no native
UI/transcript fallback for missing controller reads. It keeps at most 512 pages
for the bound v2 review; legacy phases retain their earlier 128-page limit.

`quality_review_attestation.observe` accepts a source identity, not a worker's
verdict/report. It requires the exact completed native reviewer/wakeup/realm,
latest author, consumed review capability and closed lease. Actual opened
transport, inspected immutable worker payload and successful prompt in the
registered session must already exist in the controller journal. Only then can
its durable read stream and authoritative native final output be evaluated.

The verdict is exact bounded JSON. Approval has no unresolved findings and binds
all criterion IDs, plan, Red and manifest. Change requests require actual line
quotes and, for a named test, a line within that real method's AST span. A valid
change request returns to the original author without granting test weakening or
product edits. Identity/read/protocol failures and technical escalation belong
to the CTO, never automatically to the CEO. Ending with ordinary text cannot
approve the test phase.

An approved receipt freezes every test hash, criterion witness, native execution,
read digest and review decision. `tests_frozen` authorizes no worker execution,
Green claim, merge or delivery by itself; the next implementation admission
adapter must authenticate this exact receipt and preserve its tests. Terminal
receipts survive restarts/retirement without native API reads or rerunning work.
Unknown native/close observations use a persistent original window: alert after
ten minutes, technical hold for the CTO after thirty. Only proved sealed operator
downtime extends it. Restarting does not reset the deadline or execution budget.

These native identity/verdict checks currently have database/Docker fixtures,
not a real-agent approval qualification. A real Docker/ACP run additionally
confirmed complete-copy metadata and byte-bound reads from actual Hermes
handlers. Those reads come from a **fixed operator canary**, not a model prompt
or native controller-stream verdict, and cannot freeze tests. The controller
remains sealed/default-off until native qualification and subsequent gates pass.

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
still does not mint `tests_only_v2` capabilities. Source now connects the fixed
copy producer to v2 reconciliation and independent review launch, but native
review/read attestation still needs native qualification, and subsequent gates
remain to implement and qualify.
Do not populate scope/proof tables manually to bypass these missing stages or
enable v2 based on observer/ingestion tests alone.

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
launch-time reauthentication and transport are now wired and qualified together
on synthetic native identities with actual Docker/ACP. Installed/native-agent
qualification remains pending. The installed legacy launch fence is unchanged.

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

### Opt-in native launch integration (installed, execution disabled)

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

### Bootstrap observations and acknowledgments

A qualified watchdog observation may arrive before the Docker create/start ACK.
The controller must not downgrade an already observed running worker to an ACK
or reject that stronger fact solely because of ordering. Accepting the earlier
observation requires the exact request, payload digest, container, image, native
running state and a persisted matching policy receipt. Missing or conflicting
evidence, terminal tasks and unknown start outcomes remain blocked. The start
intent is still single-use; this reconciliation never sends another command.
Native authority is checked again after a slow creation, before starting it.

Future bootstrap failures record the internal phase, exception class, source
basename/function/line and message hash. Exception text, locals, tokens and
absolute paths are not exported. These diagnostics cannot retroactively identify
the cause of a historical failure or authorize a rerun. A review admitted but
failed before ACP requires separately qualified recovery with the old execution,
capability, snapshot and attestation preserved, not a pre-admission reset.

### Evidence for requesting changes versus approval

Approval requires authenticated complete reads of the entire registered snapshot.
A concrete rejection grants no execution or approval authority. It may stop after
complete, byte-bound reads of every new test and every cited file; omissions in
other files are never represented as complete review. A cited Python helper in
a new-test file must exist in the observed AST and contain the quoted line.
Unknown functions, unread citations, incomplete new tests and stale snapshot
identities remain rejected. Escalation does not bypass the full-read check.

The source implementation reports the exact read scope. Existing blocked
attestations remain immutable; this change does not retroactively approve or
reclassify them. A request-changes record must still reach the original author
through a separately qualified revision adapter, with a new immutable submission,
new Red and new independent review before implementation can be admitted.

`quality_test_revision.py` implements that adapter in source. Corrections are
separate native tests-only tasks on the same issue/run/plan and original author.
The new workspace is seeded only with manifest/hash-verified NEW tests from the
rejected snapshot. Baseline files and product stay locked. A supplementary
rejection diagnosis may qualify an actual request-changes output previously
blocked by the full-read rule, but only after all new-test/citation reads and
native/ACP/lease provenance pass. The old attestation remains unchanged; no
approval is inherited. A prepared diagnosis never creates a task or capability.

The coordinator respects existing capacity, persists intent before dispatch,
observes the same marker after uncertain acknowledgments and escalates failed
admissions. A malformed diagnosis latches a CTO hold rather than looping. An
unchanged correction cannot rerun Red. Each new snapshot requires its own Red,
review and freeze. Old task exclusions are exact authenticated lineage records;
unknown extra runs or late state changes fail closed. There is no global
handoff limit or implicit conversion to implementation authority.

The physical revision canary uses explicitly synthetic rejection authority,
real Docker seed/lock and actual handlers/ACP without prompts or model calls.
It never establishes native reviewer approval or an autonomous delivery.

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
