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

## Qualification boundary

This mechanism is bounded provider recovery, not general zero-intervention
autonomous delivery. End-to-end product repair, deployment, QA, recovery under
faults and memory across profiles still require their own execution evidence.
