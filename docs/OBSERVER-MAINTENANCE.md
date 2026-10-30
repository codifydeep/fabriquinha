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
passed 528 tests; this is not a count of autonomous deliveries.

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

## Diagnostic context and remaining recovery boundary

Diagnostics must read and validate the exact inactive source contract and its
independently reviewed maintenance authority. They receive the same bounded edit
scope as the author. A passing historical suite is expected, not a reason to add
new assertions or manufacture feature Red. The browser harness is injected by
the fixed validator; its absence in the exploratory shell does not authorize
framework edits.

This context does not reset exhausted retries. A held maintenance incident still
requires a qualified continuation before another author attempt. The current
end-to-end maintenance path is not yet qualified: protocol handoff failures and
an earlier generic CTO diagnosis remain preserved, not converted into approval.
