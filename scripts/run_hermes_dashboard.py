"""Serve the official Hermes dashboard for observation of an existing installation.

The dispatcher remains the sole execution owner. This HTTP surface rejects
mutations and chat/terminal WebSockets; use the approved channel for commands.
"""
import argparse
import os
from pathlib import Path
import sys


class ObservationOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket' and scope['path'] != '/api/plugins/kanban/events':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        if scope['type'] == 'http' and scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
            from starlette.responses import JSONResponse
            await JSONResponse({'detail': 'Observation-only dashboard. Use the authorized /fabrica channel.'},
                               status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--port', type=int, default=9119)
    args = parser.parse_args()
    root, upstream = args.root.resolve(), args.upstream.resolve()
    if not (root / 'home/kanban.db').is_file():
        parser.error('Existing installation Kanban required; will not create another board.')
    sys.path.insert(0, str(upstream))
    os.environ.update(HERMES_HOME=str(root / 'home'),
                      HERMES_KANBAN_DB=str(root / 'home/kanban.db'),
                      HERMES_KANBAN_BOARD='default', HERMES_DISABLE_LAZY_INSTALLS='1')
    from hermes_cli.web_server import app, start_server
    app.add_middleware(ObservationOnly)
    start_server(host='127.0.0.1', port=args.port, open_browser=False, isolated=True)


if __name__ == '__main__':
    main()
