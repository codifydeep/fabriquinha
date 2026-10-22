# Quality lifecycle v2

Status: owner-approved design; policy, offline sensitivity executor and persistent
operator enrollment implemented in source. The legacy admission fences are also
implemented in source. Not installed, enrolled or enabled in the running
controller. Historical runs retain v1.

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

### Immutable enrollment and legacy fences

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
