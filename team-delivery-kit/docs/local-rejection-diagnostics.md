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

The new installed proxy diagnostic was verified by a real local HTTP canary:
rejection persisted, no retry or delivery approval, zero model calls spent.
This verifies diagnostics only, not autonomous delivery or product homologation.
