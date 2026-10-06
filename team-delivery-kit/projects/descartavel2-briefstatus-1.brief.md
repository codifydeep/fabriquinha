# BRIEFSTATUS-1 — Brief-driven dependent delivery qualification

## CEO request

Improve the existing disposable feedback board with a visible service-availability
indicator. This is a new feature; do not rebuild or replace the board.

Add GET /service-status: HTTP 200, application/json, exactly
{"status":"available"}, without additional fields. A query string such as
/service-status?probe=1 must have the same result. Keep every existing route and
feedback behavior unchanged.

On each real page load, the browser must request /service-status once and show
an accessible element with id="service-status" and role="status". Its initial
text is exactly "Checking service…" (Unicode ellipsis). After the successful
response, display "Service available". If the request fails, is non-200, or its
JSON is not exactly {"status":"available"}, display "Service unavailable".
Never lock the feedback form, clear a draft, or change filters/search/sorting
while the indicator updates. Two browser contexts must remain independent.
The indicator is not a continuous uptime monitor and needs no new polling.

Deliver an API card first, then a dependent frontend card, with genuine TDD,
independent immutable reviews, all regression tests, GitHub CI, and Docker/browser
homologation at the same final merged commit. Preserve every preexisting test.
Do not announce delivery before the deployed QA passes.

## Decisions delegated to the team

Product refines acceptance without adding new product scope. CTO owns technical
choices and resolves technical conflicts; do not ask the CEO to choose a stack.
Keep the actual Python standard-library HTTP server and vanilla browser client.
Tech Lead produces exactly C1 backend_data and C2 frontend depending on C1.
Each card must add one new discoverable Python unittest file; use the existing
full-suite command and baseline harnesses. Backend code scope: app/server.py.
Frontend code scope: app/static/app.js, app/static/index.html, app/static/style.css.
Choose actual test filenames and implementation design. Controller-owned
independent QA templates, ports, registries and credentials cannot be modified.

## Qualification boundary

Only codifydeep/descartavel2. No Truco work, cloud infrastructure, secrets in
artifacts, skipped tests, review self-approval or model-generated execution claims.
The synthetic CEO request above authorizes this disposable qualification; it
does not stand in for approval of a new Truco product brief.
