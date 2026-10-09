# Evidence-bound QA protocol recovery

Provider transport failures and product failures are different incidents. A
transport fix does not approve the product, invalidate historical failures or
authorize an implementer to modify an independently reviewed snapshot.

## Bounded recovery

The supervisor may resume observation of a blocked sequence only after verifying:

1. The original CTO execution failed with the supported transport signature.
2. Its planning lease is closed and its artifact reads were verified.
3. The installed proxy image and protocol modules match the qualified source.
4. A counted, synthetic provider fixture passed the canonical response validator.
5. One separate read-only CTO recovery execution exists for that incident.

The fixture is not delivery evidence. An unknown fixture outcome is not retried
blindly. The failed execution remains preserved, and the recovery cannot grant
write permission, a product retry, merge authority or release approval. A failed
recovery stays visible rather than spawning identical diagnostic executions.

## Historical approval versus live routing

Disabling a delivery route can project its current handoff as `paused`. This is
not a revocation or creation of a historical independent review. The QA gate
persists an exact transition proof before changing routing state. Recovery of an
older transition requires read-only verification of the approved snapshot,
author, reviewer, manifest, complete inspection receipts and completed native
executions. Changed identities fail closed.

## Scenario repair versus product repair

A controller-owned browser recipe may be corrected after a technical diagnosis.
The original failed receipt remains immutable. A scenario resolution requires a
new passed browser receipt on the same product commit, image and deployment,
including cleanup and screenshot integrity. It merely permits normal delivery
gates to run again; it is not release approval.

A corrected recipe that reveals a product defect cannot resolve the incident.
The defect requires a new TDD delivery and independent review. Combined feature
states must be exercised: separate filter and search checks do not prove their
composition works.

After an evidence-read, completed blocked CTO diagnosis, the supervisor may
create one separate `O1` read-only diagnosis for a new failed observation. The
current scenario hash must differ, while commit, application image, deployment,
browser configuration and temporary runtime environment must remain identical.
Cleanup must have passed. A frozen proof binds both observations and the prior
decision; changed proof or another observation requires technical replanning,
not another identical execution. Existing diagnostic artifacts are never rebound
once their card has a run. An `O1` repair proposal still passes through the normal
TDD contract derivation, independent review, CI and QA gates.

## Technical decision authority

New CTO diagnosis cards use decision contract v2. A scoped repair proposal is
not an executed implementation or a release approval. Controller-executed QA
and actual code inspection can justify proposing a new regression test and
repair; the CTO must not wait for authorization from its own role. Missing
evidence, real infrastructure dependencies and changes outside the allowed
scope can still block the decision. Existing cards retain their original
contract version and immutable artifacts.

For a verified completed `O1` decision that explicitly waits for CTO approval
from the CTO itself, the supervisor may create one `D1` clarification. It binds
the prior decision, verified reads, unchanged QA scenario, product commit and
image, and the clarified contract hash. This is a protocol correction, not an
automatic conversion of `blocked` to `repair`. The CTO must decide again. A
failed or still-blocked clarification remains visible without repeated runs or
an automatic request to the CEO. Any resulting proposal retains all normal
TDD, independent review, CI and deployment gates.

A repair is a new delivery card, not a continuation of the parent card's
planned dispatch. Its subprocess environment removes the parent's existing
issue ID, expected plan hash, test-revision ancestry and fault-injection flags.
The new pinned contract and run spec define its identity. Repository, Docker
instance and model-budget configuration remain inherited. Both bootstrap and
delivery reconciliation use this same environment boundary; planned-card
identity checks are not relaxed.

## Omitted independent review preconditions

Repair review policy v2 spells out the exact registered offline suite command;
prepared v1 contracts remain frozen. An implementer's Green receipt does not
replace the reviewer's own execution-scoped receipt. The broker presents the
registered command and mandatory read paths, not arbitrary reviewer commands.

If a completed independent reviewer attempts approval while its suite capability
is still merely `issued`, the outcome is review infrastructure/protocol failure,
not a demonstrated product defect. One fresh read-only review may be prepared
after verifying the closed reviewer lease, immutable source and manifest,
registered inspection scope, intact baseline and absence of an accepted review.
The original incident remains preserved; retry counters are not reset and the
author is not restarted. Approval still requires complete actual reads and a
successful independent suite. Repetition escalates technically. A technical
decision may not request product correction solely to resolve review
infrastructure.

## Qualification boundary

This mechanism is bounded recovery, not general zero-intervention autonomous
delivery. A disposable brief with two dependent cards has completed an actual
TDD product repair, complete independent inspection and reviewer-owned suite,
PR/CI integration, deployment and both baseline and feature browser QA on the
same merged commit and image. The historical failures remain preserved. Operator
infrastructure corrections were required during that cycle: it does not qualify
a fresh uninterrupted brief, arbitrary fault recovery or memory across profiles.
