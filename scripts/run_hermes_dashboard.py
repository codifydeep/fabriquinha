"""Serve the official Hermes dashboard for observation of an existing installation.

The dispatcher remains the sole execution owner. This HTTP surface rejects
mutations and chat/terminal WebSockets; use the approved channel for commands.
"""
import argparse
import os
from pathlib import Path
import sys


KANBAN_NOTICE = '''<aside role="note" style="position:fixed;bottom:8px;left:260px;right:20px;z-index:10000;background:#172033;color:white;padding:12px;border:1px solid #64748b;border-radius:8px;font:13px/1.5 system-ui">
<strong>Fabriquinha · Hermes + Kanban · consulta</strong><br>
O dispatcher Fabriquinha executa a equipe. “Gateway: Off” refere-se ao gateway nativo.
Cards históricos não indicam trabalho ativo: confira o recibo da release e seus sucessores.
Comandos e aprovações: Telegram /fabrica.
<button onclick="this.parentElement.remove()" aria-label="Fechar orientação">Fechar</button></aside>'''.encode()


class KanbanGuidance:
    """Explain native labels without changing cards or bypassing native auth."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'GET' or scope.get('path') != '/kanban':
            return await self.app(scope, receive, send)
        pending = []
        async def capture(message):
            pending.append(message)
        await self.app(scope, receive, capture)
        start = next((m for m in pending if m['type'] == 'http.response.start'), None)
        headers = dict(start.get('headers', [])) if start else {}
        if (start and start['status'] == 200 and b'text/html' in headers.get(b'content-type', b'')
                and b'content-encoding' not in headers):
            body = b''.join(m.get('body', b'') for m in pending if m['type'] == 'http.response.body')
            if b'</body>' in body:
                body = body.replace(b'</body>', KANBAN_NOTICE + b'</body>', 1)
                start = dict(start, headers=[(k, v) for k, v in start['headers'] if k.lower() != b'content-length']
                             + [(b'content-length', str(len(body)).encode())])
                await send(start)
                await send({'type': 'http.response.body', 'body': body})
                return
        for message in pending:
            await send(message)


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
    app.add_middleware(KanbanGuidance)
    app.add_middleware(ObservationOnly)
    start_server(host='127.0.0.1', port=args.port, open_browser=False, isolated=True)


if __name__ == '__main__':
    main()
