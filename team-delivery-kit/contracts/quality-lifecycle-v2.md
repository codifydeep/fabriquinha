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
    T[Tests-only snapshot] --> R[Actual full-suite Red]
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
