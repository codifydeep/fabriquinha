# BRIEFLATEST-1 — Newest matching feedback

## CEO request

Add the server-backed identity of the newest feedback matching the board's
selected status and search. Preserve every existing feature and test, including
count and read-only details. This disposable qualification does not change Truco.

GET /feedback/latest returns HTTP 200, application/json, exactly {"latest_id":N}:
N is the highest positive integer ID among matching items, or null if none.
Use the same trimmed Unicode case-insensitive title search and status semantics
as /feedback/count. Missing status means all; open and completed select a state.
Explicit empty, all, unknown or repeated status returns HTTP 400 with exactly
{"error":"Invalid latest filter"}. Missing/blank q matches all; ignore unrelated
parameters. GET never changes items, counts or summaries. Preserve old responses.

Show id="feedback-latest-match", role="status", aria-live="polite". Initially and
while a current request is pending show "Newest matching: …". Exact successful
JSON shows "Newest matching: #N", or "Newest matching: —" for null. Failed HTTP,
network, malformed JSON, extra/missing fields, arrays, boolean, zero, negative,
noninteger or string ID shows "Newest matching unavailable". Use the endpoint,
not a client-computed ID. Status/search changes refresh the composed query.
Sorting never changes the highest matching ID. Reuse existing polling, without
new timers or increased frequency, including updates from another browser.
Keep each browser's local filters, searches, drafts, detail panel and submit/busy
behavior. Requests never write or disable the form. An older query must never
render over a newer query, even briefly. Later valid responses recover normally.

## Team authority

Product refines this request without expansion. CTO chooses implementation in the
existing Python stdlib/vanilla web stack. Tech Lead creates two cards: C1
backend_data (only app/server.py plus one NEW discoverable Python unittest file);
C2 frontend (only app/static/app.js, index.html, style.css plus one NEW discoverable
Python unittest file), depending on C1. Preserve every baseline test byte-for-byte.
No new dependencies, authentication or infrastructure. Technical decisions belong
to CTO/Tech Lead, not CEO. Historical context is advice, never current approval.

## Exit criteria

Red before code edits, frozen-test independent review, Green/full suite, immutable
code review with exact-manifest offline test receipt, product PR/CI, same-commit
Docker and legacy/detail/count/latest browser QA. Preserve failed evidence.
Controller owns credentials, guards, deployment and QA. This fresh cycle tests
zero operator repair during execution and real cross-profile memory consumption.
Any operator repair means that autonomy criterion failed, even if delivery later
succeeds. A response ending or partial API delivery is not a completed version.
