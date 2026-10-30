# Scoped maintenance of delivered Python observer fixtures

This is an explicit exception for the shared browser-error observer, not general
permission to edit frozen Python tests. Hermes + Kanban remain the execution
owner; no service, database or alternative delivery pipeline is added.

## Admission and unchanged business scope

The operator-only `intake start-maintenance` operation identifies a stable request,
label, accepted source receipt and one or two existing acceptance files. The source
must be the latest natively accepted release. No active release or unfinished
worker may exist. The source commit must still be the remote base when the graph
is materialized. Retrying the same request resumes the same anchor and plan;
changing the request body under the same key is rejected.

The immutable `maintenance_authorization` records operator scope and explicitly
sets `business_change=false` and `delivery_approval=false`. The original approved
brief is retained as historical business scope, without forging another product
brief or CEO approval. New behavior is outside this path.

## Existing team and gates

The Tech Lead proposes one package covering the existing brief. The CTO reviews
that plan independently. QA authors the candidate; its independent reviewer
freezes only the exact reviewed revision. The implementation phase preserves the
product byte-for-byte, executes Green and all existing required negative controls.
The original PR, exact-SHA local CI, integration, deploy, rollback and deployed QA
gates remain mandatory. An accepted maintenance scope does not close a release.

Only `open_home` and `full_room_pair` may receive the exact shared-observer
substitution. Test methods, assertions, imports, other helpers, manifest files,
discovery, configuration and product files are unchanged. Only those two files
lose their baseline read-only mount in the author phase; reviewers still read an
immutable snapshot. The whole snapshot is checked, not only a submitted diff.

A new `test_revision` records fresh original/revised full-suite jobs. Historical
Red is explicitly historical; passing maintenance is not claimed as a new feature
Red. No old receipt is reinterpreted as a new permission. CI recognizes the scoped
substitution only after the new independent freeze. Self-review, stale handoffs,
foreign job bindings and product changes are rejected.

In addition to retained control targets, a product-only negative control must fail
the preserved `pair['errors'] == []` assertion in **each** repaired fixture. The
controller checks actual assertion frames against the immutable test AST. Other
failures cannot substitute for this observer proof.

## Qualification boundaries

Offline tests cover scope, identity, exact revision, independent freeze, stale
handoffs, full snapshot protection and product immutability. The native proof
uses a private copy of an accepted board: repeated admission and graph recovery
produce one plan and one graph, with a separate CTO reviewer. Roles in that proof
are programmed, not model judgments.

The Chromium proof uses a disposable synthetic HTTP app and four isolated Docker
jobs: old/new normal behavior passes; late errors after setup are blocked by the
central observer with the old fixture and by the preserved assertion with the
repaired fixture. It does not modify product workspaces or snapshots and consumes
no model calls. These proofs qualify the narrow mechanism, which is installed in the reference
environment. The actual agent repair has been admitted; its freeze, PR and new
homologation must still supply their own evidence. The complete offline suite
passed 532 tests; this is not a count of autonomous deliveries.

## Operator interface

Prepare a private JSON request containing `request`, `label`, `acceptance` and
`paths`. From the verified installed source and SDK environment, use:

```sh
python -m fabriquinha.intake start-maintenance \
  --root /absolute/installation --upstream /absolute/pinned-hermes \
  --file /absolute/private-maintenance-request.json
```

This operation is not an agent tool or a general Telegram approval command. The
ordinary native board, durable outbox and `/fabrica status` expose subsequent work.
No token, installation state or source receipt contents belong in the repository.

## Diagnostic context and bounded replanning

Diagnostics must read and validate the exact inactive source contract and its
independently reviewed maintenance authority. They receive the same bounded edit
scope as the author. A passing historical suite is expected, not a reason to add
new assertions or manufacture feature Red. The browser harness is injected by
the fixed validator; its absence in the exploratory shell does not authorize
framework edits. Plan and diagnostic evidence includes read-only `AcceptanceTest`
and `acceptance_evaluate` source excerpts from the installed validation bundle,
with its bundle identity and browser file hash. These excerpts explain the
interface; they never replace executing the required negative controls.

This context does not reset exhausted retries. The operator may use
`intake replan-maintenance` with a private JSON containing `release` (the root
card) and `diagnosis` (the exact completed CTO hold receipt). Admission requires
an unchanged single-package graph, a settled tests author in triage, no active
workers or unresolved source effects, and no downstream execution.

One successor plan is keyed to the predecessor graph. The Tech Lead must name
both authorized test paths; the CTO reviews the proposed scope independently.
Mentioning paths is only a structural gate, never semantic approval. Until that
review completes, no successor delivery graph is released. New cards and
workspaces preserve the original graph, incident, attempts and decisions. A
crash between native plan creation and pointer persistence reuses the same plan.
A different diagnosis cannot silently create repeated replans for that graph.

The isolated native proof covers interrupted admission, active-worker refusal,
independent review, repeated graph materialization, separate workspaces and
unchanged predecessors. It uses programmed roles and does not qualify autonomous
agent performance. The live repair still requires fresh freeze, controls, PR,
CI, deployment and QA. This administrative replan is assisted recovery.

## Corrected environment, unchanged reviewed plan

`intake resume-maintenance-environment` accepts an exact root card and completed
CTO hold receipt. It is a bounded operator admission, not an agent retry tool.
It requires the corrected independently reviewed plan, settled tests triage,
unchanged workspace, no downstream execution or unresolved effects, and the
actual old sandbox identity proving the pinned browser source was absent.
The installed sandbox command must now mount that exact validator read-only at
`/opt/fabriquinha/browser.py`. No framework import or product change is required
for file/line inspection. Network, credentials and Docker remain unavailable.

Admission preserves the existing plan approval and all predecessor cards. It
records the changed environment and creates fresh graph-owned cards/workspaces,
without resetting a breaker or granting test, review or delivery approval. One
such succession is allowed per root; another diagnosis cannot silently repeat it.
The native isolated proof checks idempotence, crash recovery, unchanged history
and reuse of the independent plan. The real Docker mount proof verifies readable
bytes and an EROFS refusal on attempted writes. These proofs do not qualify the
actual fixture repair, which still requires every delivery gate.
