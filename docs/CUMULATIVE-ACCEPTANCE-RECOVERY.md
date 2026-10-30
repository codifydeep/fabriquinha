# Cumulative acceptance capacity and rejected submissions

The Python acceptance inventory is cumulative across delivered increments.
Its resource bounds are 256 unique criteria and 1024 cases, separately from the
bounded current product brief. Existing criteria, cases, assertions, discovery
and baseline bytes remain protected. Bounds never authorize dropping regressions.
An overflow reports the actual count and limit and requires technical escalation.
Legacy declarative browser contracts retain their existing bounds.

A rejected `delivery_submit` in the tests-author phase stores the candidate and
baseline snapshot IDs, exact execution, phase and error in a durable refusal.
Recovery receives that refusal even when the workspace later returns to baseline.
Earlier same-card/contract refusals are explicitly historical. A green baseline
diagnostic does not establish that a rejected candidate was valid or absent.
Snapshots are evidence, never approval, freeze or authorization to weaken tests.

## Assisted capacity repair

An operator-authorized `repair-capacity` is restricted to an active approved plan
whose first tests card reached triage, with a completed CTO hold and no downstream
execution, active worker or pending source effect. Dispatch must be paused.
The retained additive candidate must reproduce the old inventory error under the
old pinned validator and pass the new inventory validator. Every baseline and
product byte must remain identical; the fixed suite runner must also be unchanged.
This static preflight is not behavioral Red or delivery acceptance.

The controller records the old/new validator pins and creates a new graph from the
same approved plan and seed. Old cards, runs and receipts remain unchanged. The
new graph is marked assisted, including its eventual release acceptance. Workers
receive the rejected-attempt context, but must author/submit real evidence through
all usual TDD, independent freeze, review, PR, CI, deployment and QA gates.
No retry counters are reset and no old quality receipt becomes newly valid.
Admission and successor creation are idempotent; an interrupted pin installation
must finish under maintenance before dispatch resumes.

Offline qualification covers cumulative limits, preserved baseline inventory,
rejected snapshot retention, foreign-execution rejection, a copied native board,
installation interruption/restart, unchanged predecessors, one successor graph,
and two dependent increments. These checks do not qualify autonomous delivery.
