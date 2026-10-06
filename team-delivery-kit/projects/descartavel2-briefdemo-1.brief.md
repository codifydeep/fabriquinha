# BRIEFDEMO-1 — Fresh brief, no operator handoffs

## CEO request

Extend the existing disposable feedback board with a visible demo-environment
indicator. Preserve the service-availability indicator and every existing feature.

GET /service-mode must return HTTP 200, application/json, exactly {"mode":"demo"},
with no extra fields. /service-mode?probe=1 must behave identically.

On each page load request /service-mode once. Show an accessible element with
id="service-mode" and role="status", initially "Checking environment…" (Unicode
ellipsis), then "Demo environment" for exactly {"mode":"demo"}. A failed request,
non-200 response, malformed JSON or extra fields must show "Environment unavailable".
No new polling. Never lock or submit the feedback form, clear drafts, or alter
search, filters or sorting. Two browser contexts must remain independent.

Deliver API first, then its dependent web indicator, with genuine TDD, independent
immutable reviews, complete regressions, GitHub CI and Docker/browser QA on the
same final merged commit. Preserve every preexisting test byte-for-byte.

## Delegated decisions

Product refines acceptance without expanding scope. CTO resolves all technical
questions; retain the Python standard-library HTTP server and vanilla browser
client. Tech Lead produces exactly C1 backend_data and C2 frontend depending on C1.
Each card adds one concise discoverable Python unittest file, chosen by the team;
reuse existing harnesses and the full-suite command. Backend code scope:
app/server.py. Frontend code scope: app/static/app.js, app/static/index.html,
app/static/style.css. Ports, independent QA, registries and credentials are
controller-owned. Do not change them or invent tool executions.

## Qualification boundary

Only codifydeep/descartavel2; no Truco, paid infrastructure or secrets in artifacts.
This synthetic request authorizes the disposable test, not a Truco release.
Start from the previous homologated main; do not reset the project or old cards.
Success requires the whole brief delivered without operator-directed handoffs.
An unresolved failure remains visible, never reported as delivery.
