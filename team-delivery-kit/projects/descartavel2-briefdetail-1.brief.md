# BRIEFDETAIL-1 — Independent item detail

## CEO request

Extend the disposable feedback board with a read-only detail view. Preserve all
existing behavior and tests; no authentication or new infrastructure.

GET /feedback/<id> returns HTTP 200, application/json, exactly
{"item":{"id":<integer>,"title":<string>,"completed":<boolean>}} for an existing
positive integer id. A query string does not change that result. Unknown positive
ids return HTTP 404 with exactly {"error":"Feedback not found"}. Noncanonical
ids (zero, negative, leading zeros, letters) return HTTP 400 with exactly
{"error":"Invalid feedback id"}. Preserve /feedback and /feedback/summary.

Each listed item has an accessible button named "View details". Clicking opens
one local panel with id="feedback-detail", role="region" and aria-label="Feedback
details", initially "Loading details…". Fetch that item's detail once per click;
show its literal title and "Open" or "Completed". A button "Close details" closes
the panel without clearing the title draft or changing search, filter or sort.
No page navigation, form submit, completion or new polling. Different browser
contexts remain independent. A failed request shows "Details unavailable" without
disabling the feedback form. When selecting a different item or closing while
a request is pending, stale responses must not reopen or overwrite the panel.
Render titles as text, never executable HTML. Keyboard activation must work.

Deliver API then dependent web behavior with Red-Green-Refactor, independent
immutable review, full regressions, GitHub PR/CI and exact-commit Docker/browser
QA. Never weaken or remove baseline tests. Completion requires the whole feature,
not merely workers running or tests reporting success.

## Decisions delegated to the team

Product refines the request without expanding scope. CTO owns technical decisions
and retains Python stdlib HTTP plus vanilla browser code. Tech Lead creates C1
backend_data and C2 frontend depending on C1. Each card chooses one concise new
discoverable Python unittest file and uses existing HTTP/JS harnesses. Backend
edits only app/server.py; frontend edits only app/static/app.js, index.html and
style.css. Controllers own ports, credentials, QA recipes and publication gates.

## Qualification boundary

Only codifydeep/descartavel2. Start from the homologated main, never reset old
cards, commits or evidence. This synthetic brief authorizes the disposable test,
not Truco. A repaired execution does not prove an intervention-free cycle.
