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
offline, credential-free disposable container. It is not yet activated in the
production worker image. Activation requires the maintenance barrier, verified
backup, pinned image build and installed-code qualification. It does not repair
or retrospectively approve a previous failed delivery.
