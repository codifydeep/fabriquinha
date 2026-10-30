# Local Hermes Kanban

The installed observation dashboard is available at
[http://127.0.0.1:9119/kanban](http://127.0.0.1:9119/kanban).
Select the `default` profile and `Default` board. Search by card ID or title;
opening a card shows its events, result and run metadata. The release card for
v0.2 shows `HOMOLOGADA` in its final result.

`scripts/run_hermes_dashboard.py` serves the official UI and API from the pinned
Hermes checkout. It binds only to loopback and requires an existing installation
`home/kanban.db`; it never creates a substitute board. The dashboard uses a
separate Python environment with the pinned upstream web extras and a built
upstream web bundle. The local LaunchAgent starts it again after login.

The HTTP wrapper allows observation and Kanban events, but rejects mutations and
chat/terminal WebSockets. Dispatch and approval continue through the existing
controller and authorized `/fabrica` channel. Native buttons for editing,
archiving, nudging, configuring or starting chat are not supported on this
observation surface. No model call is required to inspect cards.

The generic Hermes sidebar reports its own gateway, not the separate Fabriquinha
channel/dispatcher. `Gateway: Off` therefore does not prove the team is stopped.
Likewise, native orchestration labels describe Hermes defaults, not the
controller's effective policies. Historical superseded cards remain visible;
the release acceptance and successor graph determine current delivery state.

Telegram is not mirrored into the Hermes chat view. Commands and notifications
use the scoped channel; durable card events and agent run metadata are separate.

## Reproduce

Build the web workspace of the pinned Hermes checkout using its official build
script. Install its `web` dependencies in an isolated environment with the same
Python version and access to the SDK dependencies. Then run:

```sh
python scripts/run_hermes_dashboard.py \
  --root /absolute/path/to/installation \
  --upstream /absolute/path/to/pinned-hermes --port 9119
```

Do not run another gateway or dispatcher to enable the dashboard. Preserve the
pinned checkout's tracked sources when installing Node dependencies.

## Multica retirement

The retired `eval` and `port2` stacks are not used by this path. Their host
LaunchAgents were disabled and archived, databases dumped and verified, and
container metadata/logs archived privately before exact-ID removal. Volumes and
historical evidence remain available for recovery. Shared images and unrelated
projects must not be removed as part of retirement.

The Kanban page includes a dismissible explanation of these ownership and history
limitations. This static notice is not a health indicator or release summary.
