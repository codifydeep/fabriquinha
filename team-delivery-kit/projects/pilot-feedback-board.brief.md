# Product pilot brief — local feedback board

Purpose: qualify the agent team's ability to turn a short product request into
a working, locally deployed web application. This is a disposable platform
evaluation in `codifydeep/descartavel2`, not part of Truco Online.

## CEO request

Build a small feedback board for a two-person team. A person opening the local
URL can see suggestions, add a suggestion with a short title and description,
and mark one as completed. A second browser must see the change without a
manual server restart. Data must survive an application-container restart.
No account or cloud service is required.

## Acceptance outcomes

1. A fresh local deployment opens a usable page in a desktop browser.
2. A visitor can create a suggestion. Empty titles and duplicate submissions
   are handled clearly.
3. Suggestions appear to both browsers; completion state is consistent after
   refresh and across browsers.
4. Suggestions and completion state survive a controlled application restart.
5. Automated unit, API, integration and browser tests cover the acceptance
   outcomes and preserve all pre-existing repository tests.
6. The team records Red, Green and full-suite evidence for each code change;
   an independent reviewer approves each exact delivery revision.
7. The version is deployed on Docker locally and QA verifies the running
   application at the integrated commit. The final handoff includes URL, SHA,
   PRs, tests, known limitations and a tested rollback procedure.

## Decisions delegated to the team

Product may clarify wording and edge cases. CTO selects a free local stack and
decides architecture/security tradeoffs. Tech Lead plans dependencies and
integration. DevOps designs local persistence, health checks and rollback. QA
defines independent verification. The team decides whether operational or
product events are useful and records that decision with the feature.

The CEO is asked only about user-facing behavior or a change to the approved
scope. Technical choices and routine failures are resolved by Tech Lead and CTO.

## Qualification rules

The operator may bootstrap the disposable repository and bounded platform
permissions, but must not handwrite feature-level contracts or implementation
cards for this pilot. The team must produce the plan and cards from this brief.
One deliberate technical failure and one controller restart are injected during
delivery. Completion requires the full application in local homologation; a
working API or isolated page is only intermediate progress.
