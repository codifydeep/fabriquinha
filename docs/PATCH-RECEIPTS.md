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

### Diagnosis transport recovery

The diagnostic prompt uses the existing non-executing typed technical submission,
with no filesystem or terminal tools, a 1,200-character hard limit and a shorter
target. This limit matches the installed proxy schema. A length-rejected plain
JSON diagnosis may qualify exactly one changed-transport diagnosis, not an author
retry. Registration verifies the actual closed native execution, the owned proxy
rejection and its installed schema projection before creating another intent.
The first failed task, wakeup and hold remain preserved; the recovery has its own
hash-bound marker and persistent state. A second failure remains a visible hold.
Neither a diagnosis nor successful transport grants fresh Red, review approval,
implementation permission or release completion.

### Synthetic persistence controls

`team-delivery-kit/run_patch_persistence_probe.py --image sha256:<local-image-id>`
runs the installed Hermes patch handler and ACP formatter on a disposable sample.
The container has no network, credentials, Docker socket or product mounts; its
only write-safe root is a temporary tmpfs. Controls measure hashes before editing,
immediately afterward and from a fresh process, including an actual reverse patch.

An installed handler can report success with no diff and unchanged bytes without
declaring `no_change`. The classifier therefore distinguishes explicit no-op,
observed unchanged success, persistent change, later change and inconclusive
evidence. It never turns a handler success into delivery proof. These controls
qualify observation, not the historical cause of a failed product task, and grant
no author retry. The next real correction still requires source-bound observation,
fresh Red and independent review under the original contract.

### Immediate worker observations

`patch_persistence_observer` wraps only the exactly pinned installed patch handler.
It calls the original handler once, without altering arguments, write fences or
permissions. In fenced implementation mode, it observes regular Python tests of
at most 32 KiB beneath `/workspace/tests` before and after replace-mode edits.
Directory traversal, symlinks, hard links and files outside this boundary do not
produce an observation. No file content is returned; malformed observations are
not forwarded by the ACP receipt formatter.

These are immediate observations, not final snapshot evidence: a subsequent edit
can still reverse the change. Missing observations are inconclusive, not permission
to rerun an author or accept Red. Review/planning executions remain uninstrumented.
The synthetic launcher supports `--observed` to qualify the actual handler and
formatter against independently measured hashes in an isolated tmpfs workspace.
Real worker ACP persistence and source-bound recovery still require their own
end-to-end evidence; synthetic controls do not replace delivery gates.

The observed fixture is precreated by the synthetic controller as root-owned,
phase-writable data. The fixed bootstrap drops irreversibly to UID/GID 10000 before
importing or invoking the handler. This reproduces the installed in-place writer's
ownership requirement; it does not disable that guard. Only SETUID/SETGID bootstrap
capabilities are retained, and there are no product mounts or infrastructure secrets.
