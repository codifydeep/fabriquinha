# BRIEFCOUNT-1 — Matching-result count

## CEO request

Add a server-backed count of feedback matching the board's selected status and
search. Preserve every existing feature and test, including read-only details.
This disposable request authorizes the exact scope below, not a change to Truco.

GET /feedback/count returns HTTP 200, application/json, exactly {"count":N}, with
N a nonnegative integer. Count the same items returned by GET /feedback with the
same status and q. Missing status means all; open and completed select that state.
Explicit empty, all, unknown or repeated status returns HTTP 400 with exactly
{"error":"Invalid count filter"}. Search uses the existing trimmed Unicode
case-insensitive title matching; missing/blank q matches all and other parameters
are ignored. Count reads never modify items or summary. Preserve all existing
API response shapes and errors, including /feedback/<id>.

Add a visible element id="feedback-match-count", role="status", aria-live="polite".
Initially and while a current count request is pending it says "Matching: …".
A successful exact JSON response shows "Matching: N"; failed HTTP, malformed JSON,
wrong shape, boolean, negative or noninteger count shows "Matching unavailable".
Use the new endpoint, not a client-derived placeholder. Status/search changes
refresh the count with correct combined query parameters. Sorting does not change
the count. Existing polling refreshes it across browsers; do not add another
timer or increase polling frequency. Preserve each browser's local filter/search,
drafts, submitting/busy guards and detail panel behavior. Count requests never
write data or disable the form. Ignore superseded responses so an older query
cannot overwrite the selected query's count. Recovery on a later request works.

## Team authority

Product refines the approved request without expanding it. CTO chooses technical
details within the existing Python stdlib and vanilla web stack. Tech Lead
creates two cards: C1 backend_data (only app/server.py plus one NEW discoverable
Python unittest file); C2 frontend (only app/static/app.js, index.html, style.css
plus one NEW discoverable Python unittest file), depending on C1. Choose concise
new test names; do not reuse or edit a baseline test. Test actual HTTP/JS behavior
with the baseline harnesses. No new dependency, authentication or infrastructure.
No technical decision requires CEO approval within this scope.

## Exit criteria

Red before product edits, independent frozen-test review, Green and full suite,
complete immutable code review with the reviewer's own successful offline suite,
GitHub PR/CI, local Docker deployment and baseline/detail/count browser QA on the
same merged commit and image. Preserve previous evidence and all old tests.
A complete assistant response is not a delivered version. Start from the pinned
homologated main. Controllers own QA, credentials, ports, releases and guards.
This fresh cycle measures zero operator repair during execution; an infrastructure
intervention must be reported as a failed autonomy criterion, even if repaired
delivery later succeeds.

