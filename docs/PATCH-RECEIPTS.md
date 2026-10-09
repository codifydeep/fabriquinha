# Patch observability boundary

`broker/patch_receipt_contract.py` provides an exact-source build adapter for
Hermes' ACP edit formatter. It preserves a bounded JSON receipt for `patch`:
handler success, no-op, nonempty diff hash/size, and explicit non-authorization.
It does not store diff source, arbitrary error text, prompts or tool arguments.

A handler receipt is not filesystem evidence. Two successful patches may undo
each other, or an unrelated persistence problem may occur. Only the controller's
source-bound workspace/snapshot hashes, fresh Red and independent review can
qualify the resulting delivery. An unchanged repair remains rejected.

The adapter changes presentation only: handler invocation, write fences, review
restrictions, test commands, approval policy and retry budgets are unchanged.
Malformed/non-patch responses retain the original formatter. Source drift or a
second installation fails closed.

This adapter is qualified against the currently pinned Hermes formatter in an
offline, credential-free disposable container and activated in the port2 worker
image by `Dockerfile.patch-receipts-420`. Activation used the maintenance barrier,
verified backup, pinned image build and installed-code qualification. Both the
controller and Hermes import paths carry the same source. It does not repair or
retrospectively approve a previous failed delivery; the unchanged trial remains
blocked. New real worker execution must still validate the ACP receipt end to end.

## Completed unchanged repair incidents

`unchanged_repair_incident` qualifies completed, closed-lease seeded repairs
against the controller-owned copy/Red job receipts and the historical test
hash. It registers a distinct, durable CTO diagnosis while preserving the
blocked handoff. Cause remains unknown: a formatted success is not evidence
of a lasting change, and equal hashes do not prove that the agent reverted it.

The diagnosis cannot wake the author or waive Red. Either CTO action is stored
as a recommendation pending a separately qualified changed-condition experiment
against the existing plan. Failed/invalid diagnoses remain visible and cannot
rearm the incident. After an uncertain POST, only the original native marker
is observed; restart does not issue another POST or duplicate a diagnosis.
