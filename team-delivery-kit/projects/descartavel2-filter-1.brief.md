# FILTER-1 — brief-to-dependent-delivery qualification

## CEO request

Extend the existing local feedback board so users can view all, open or completed
suggestions. Opening the page shows All. Selecting Open or Completed shows only
that state, including a clear empty-result message. A selected filter survives
polling and successful creation/completion; it need not survive a page reload.
Summary counters always describe the whole board, not just the filtered list.
Changing filters must not lose a typed draft or interrupt an in-flight submit.
Two browsers may select different filters independently. Preserve existing
Escape dismissal, pending-submit protection and accessibility behavior.

The current app uses a Python standard-library server, SQLite and plain browser
JavaScript. GET /feedback lists all items; POST /feedback creates an item and
the existing completion operation changes its state. GET /feedback/summary
returns whole-board counts. Keep existing default API behavior compatible;
the team decides the filtering API details and presentation. Deliver backend
capability first, then integrate its browser consumer as a dependent card.

The baseline is commit adfcff73d626f12ed413a4010024960038b99ba1 with 154 tests.
Preserve every existing test byte-for-byte. Every code change requires new tests
first, controller-captured Red, independent test review, Green, full-suite and
immutable independent delivery review. The successor must use the predecessor's
integrated commit and preserve its new tests. Completion means local Docker
homologation, green CI and independent real-browser QA at the same final SHA,
including filter switching, empty results, polling and two-browser behavior.

## Decisions delegated to the team

Product writes acceptance criteria, CTO resolves architecture/security choices,
and Tech Lead proposes exactly two dependent implementation cards: backend_data
then frontend. Do not request technical decisions from the CEO. Use only the
existing local stack and installed tools. Do not invent evidence of execution.
The operator will not write the feature implementation or its per-card scope.
Any unsupported execution/QA capability stays visibly blocked pending platform
support, never automatically approved or reported as delivered.
