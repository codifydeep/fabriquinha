# S6: distinguish HTTP clients before declaring contradictory tests

The current fixture revision produced a real Red: 16 cases, seven behavioral
failures, no execution errors or skips. Independent review remains blocked;
implementation and integration have not started for this revision.

The technical diagnosis conflated an HTTP 409 asserted by a Python client with
an HTTP 409 received by a browser. A generic isolated Chromium experiment
(`scripts/qualify_http_client_isolation.py`) observed:

- Python received 409 while the browser console stayed empty.
- A subsequent browser fetch received 409 and generated a console error.

The probe used a disposable container without external networking, credentials
or Docker socket. It changed neither product nor acceptance tests. This disproves
the claimed necessary equivalence of those events, not the existence of every
possible product defect or race. The current test order must still be inspected.

## Next technical steps

1. Preserve the held incident, old decisions, counters and snapshots.
2. Carry the client distinction and limits of the experiment into a scoped CTO
   reassessment. Do not reset triage, approve tests manually or repeat an unchanged
   diagnostic execution.
3. CTO must decide whether the existing assertions can be satisfied, with explicit
   references to client, request and event order. Missing product behavior in a
   Red snapshot cannot establish that an implementation is impossible.
4. If feasible, obtain independent review of the unchanged tests through the
   supported recovery lifecycle, then let the author implement. Any new recovery
   transition needs offline identity, idempotency and restart qualification first.
5. Preserve full Green, negative controls, independent review, PR, exact-SHA CI,
   deployment and QA. The generic probe is never accepted as one of these receipts.

No business decision or relaxation of the quality contract is required merely
because the previous implementation produced a browser console error.
