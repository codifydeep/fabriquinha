# BRIEFDEMO-2 — Fresh brief, no operator handoffs

## CEO request

Extend the disposable feedback board with a demo-environment indicator. Preserve
the existing service-availability indicator and every other feature.

GET /service-mode returns HTTP 200, application/json, exactly {"mode":"demo"},
without extra fields. /service-mode?probe=1 behaves identically.

On each page load, request /service-mode once. An accessible element with
id="service-mode" and role="status" initially says "Checking environment…"
(Unicode ellipsis), then "Demo environment" for exactly {"mode":"demo"}.
A failed request, non-200 response, malformed JSON or extra fields says
"Environment unavailable". No new polling. Never lock or submit the feedback form,
clear drafts, or alter search, filters or sorting. Two browser contexts stay independent.

Deliver API first, then its dependent web indicator, with genuine TDD, independent
immutable reviews, full regressions, GitHub CI and Docker/browser QA on the same
final merged commit. Preserve every preexisting test byte-for-byte.

## Decisions delegated to the team

Product refines acceptance without expanding scope. CTO owns technical decisions;
retain the Python standard-library HTTP server and vanilla browser client.
Tech Lead produces exactly C1 backend_data and C2 frontend depending on C1.
Each card adds one concise discoverable Python unittest file chosen by the team;
reuse existing harnesses and full-suite discovery. Backend scope: app/server.py.
Frontend scope: app/static/app.js, app/static/index.html, app/static/style.css.
Ports, independent QA, registries and credentials remain controller-owned.

## Qualification boundary

Only codifydeep/descartavel2; no Truco, paid infrastructure or secrets in artifacts.
This synthetic request authorizes the disposable test, not a Truco release.
Start at the prior homologated main; do not reset the project or old cards.
Success requires the whole brief delivered without operator-directed handoffs.
Unresolved failure stays visible, never reported as delivery. BRIEFDEMO-1 is a
preserved input-format failure before model dispatch, not a successful agent run.
