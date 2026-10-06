# Local proxy rejection diagnostics

The proxy rejects invalid requests before spending a model call. Such a rejection
is not an agent delivery, a successful test, or permission to retry.

For correlated execution requests, local failures now create a durable
`local_request_rejection_v1` receipt in `request-rejections.sqlite`, adjacent to
the persistent model counter. Receipts contain only:

- Execution ID and request SHA-256 (not the request body).
- The failing stage, allowlisted source module and source line.
- Exception type and error SHA-256 (not the exception text).
- Explicitly false retry and delivery approval flags.

The ledger is restricted to its controller owner, deduplicated and durable.
Recording failure causes a fail-closed HTTP 503. Workers cannot use it to grant
themselves another execution. Read it with `proxy_request_rejections.read` in the
trusted proxy environment, not through an agent shell or public endpoint.

The offline history probe also checks intermediate tool-result prefixes. It is
only a reconstruction: a successful probe does **not** qualify the original RPC,
whose registry, compacted history and transport may differ.

## Current trial finding

The latest second-card test-author execution failed with a local HTTP 400 before
the next upstream call. Its failed snapshot was preserved. The offline
reconstruction, including intermediate prefixes, did not reproduce this failure.
The precise cause remains unqualified; no automatic identical retry was granted.

Further inspection found exactly 40 assistant tool turns in the failed session.
The installed native finalizer issues an extra toolless summary at that budget.
Replaying the preserved history without tools reproduces the local contract
rejection (`test artifact requires existing read and write tools`). Replays with
tools, active messages and the API-content sidecar succeed. The native registry
probe exposed 17 tools without the original worker environment, versus 18 in the
live metrics: it is not an exact original-request replay. The missing historical
payload prevents claiming an exact RPC diagnosis.

Controller workers now skip the provider summary when the normal native budget
fallback is eligible, and return `failed=true`, `completed=false`,
`failure_reason=iteration_budget_exhausted`. The ordinary finalizer cleanup and
persistence remain in place. Normal interactive Hermes behavior is unchanged.
The ACP adapter propagates this bounded classification, not prose or an `end_turn`
success. The 40-iteration limit and the independent Red/review gates remain intact.

An isolated installed-code AST probe validates the guard in implementation,
review and diagnostic modes, without any provider call. It does not qualify the
full ACP RPC or an autonomous recovery. Next: diagnose the 40-turn work pattern
and replan through CTO, rather than reset the same task budget automatically.

The new installed proxy diagnostic was verified by a real local HTTP canary:
rejection persisted, no retry or delivery approval, zero model calls spent.
This verifies diagnostics only, not autonomous delivery or product homologation.
