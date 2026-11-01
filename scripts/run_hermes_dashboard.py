"""Serve the official Hermes dashboard for observation of an existing installation.

The dispatcher remains the sole execution owner. This HTTP surface rejects
mutations and chat/terminal WebSockets; use the approved channel for commands.
"""
import argparse
import os
from pathlib import Path
import sys


KANBAN_NOTICE = '''<aside role="note" style="position:fixed;bottom:8px;left:max(8px, min(260px, 20vw));right:12px;max-height:45vh;overflow:auto;overflow-wrap:anywhere;z-index:10000;background:#172033;color:white;padding:12px;border:1px solid #64748b;border-radius:8px;font:13px/1.5 system-ui">
<strong>Fabriquinha · Hermes + Kanban · consulta</strong><br>
O dispatcher Fabriquinha executa a equipe. “Gateway: Off” refere-se ao gateway nativo.
Cards históricos não indicam trabalho ativo: confira o recibo da release e seus sucessores.
Comandos e aprovações: Telegram /fabrica. Atualizações são instaladas sob manutenção; este painel não pode atualizar o Hermes.
<button onclick="this.parentElement.remove()" aria-label="Fechar orientação">Fechar</button></aside>'''.encode()


def operational_summary(root, now=None):
    """Read-only projection: no raw done card is promoted to homologation."""
    import json, time, html, hashlib
    root=Path(root);now=time.time() if now is None else now
    esc=lambda value:html.escape(str(value),quote=True)
    try:
        status=json.loads((root/'status.json').read_bytes())
        age=now-float(status['observed_at'])
        if age<0 or age>90:
            return '<p role="status">Estado operacional desconhecido: observação desatualizada. Recarregue para consultar novamente.</p>'
        board=status['board'];cards=board['cards']
        releases=[c for c in cards if c.get('kind')=='release']
        latest=max(releases,key=lambda c:(c.get('created_at',0),c['id'])) if releases else None
        lines=['<strong>Resumo operacional · somente leitura</strong>',
            'Dispatcher: '+esc(status.get('dispatcher_state','desconhecido'))+' · observação há '+str(int(age))+'s']
        if latest:
            lines.append('Release: '+esc(latest['title'])+' · '+esc(latest['id'])+' · card '+esc(latest['status']))
            # Exact controller receipt with verified content identity; status alone is not success.
            accepted=[]
            for path in (root/'private/receipts').glob('*.json'):
                data=json.loads(path.read_bytes())
                if data.get('kind')!='release_acceptance' or data.get('binding',{}).get('task')!=latest['id']:continue
                raw=json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
                if hashlib.sha256(raw).hexdigest()!=path.stem:raise ValueError('receipt integrity')
                payload=data['payload']
                if data['binding'].get('actor')=='controller' and payload.get('state')=='HOMOLOGADA':accepted.append(payload)
            if len(accepted)==1 and latest['status']=='done':
                proof=accepted[0]
                lines.append('HOMOLOGADA · '+('ciclo assistido' if proof.get('assisted') else 'autonomia não inferida automaticamente'))
                lines.append('Commit: '+esc(proof['commit'])+' · URL: '+esc(proof['url']))
            elif latest['status']=='done':lines.append('Conclusão sem recibo único verificável: conferir evidências.')
        active=[c for c in cards if c.get('current_run_id') is not None]
        for card in active:
            lines.append('Em execução: '+esc(card['id'])+' · '+esc(card['assignee'])+' · '+esc(card['title']))
            progress=card.get('last_validation') or {}
            if progress.get('at'):
                lines.append('Última evidência validada: '+esc(progress.get('kind',''))+' · há '+str(max(0,int(now-progress['at'])))+'s')
            if card.get('technical_owner'):lines.append('Responsável técnico: '+esc(card['technical_owner']))
            if card.get('last_event_at'):lines.append('Último evento: há '+str(max(0,int(now-card['last_event_at'])))+'s (não equivale a progresso validado).')
        if not active:lines.append('Nenhum worker ativo nesta observação.')
        for name in ('release_issues','recovery_issues','integration_issues','provider_issues','settlement'):
            if board.get(name):lines.append('Atenção — '+esc(name)+': '+esc(json.dumps(board[name],ensure_ascii=False)))
        incidents=[i for i in board.get('incidents',[]) if i.get('state') not in ('resolved','superseded')]
        if incidents:
            lines.append('<details><summary>Incidentes registrados — podem incluir predecessores históricos</summary>'+''.join(
                '<p>'+esc(i.get('source'))+' · '+esc(i.get('owner'))+' · '+esc(i.get('next_action',{}).get('reason','') if isinstance(i.get('next_action'),dict) else i.get('next_action'))+'</p>' for i in incidents)+'</details>')
        notices=board.get('notifications',{})
        lines.append('Avisos: '+esc(notices.get('queued','?'))+' pendentes; '+esc(notices.get('uncertain','?'))+' com envio incerto. Incerto não significa entregue.')
        lines.append('Cards e predecessores históricos permanecem no board; este resumo não altera seus estados. <a href="/kanban">Atualizar</a>')
        return '<div role="status">'+'<br>'.join(lines)+'</div>'
    except (OSError,ValueError,KeyError,TypeError):
        return '<p role="status">Resumo indisponível: evidências ausentes ou inconsistentes. Nenhuma conclusão inferida.</p>'


class KanbanGuidance:
    """Explain native labels without changing cards or bypassing native auth."""
    def __init__(self, app, root=None):
        self.app = app
        self.root = root

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'GET' or scope.get('path') not in ('/', '/kanban', '/system'):
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
                summary=(operational_summary(self.root).encode() if self.root else b'')
                notice=KANBAN_NOTICE.replace(b'<strong>',summary+b'<hr><strong>',1) if summary else KANBAN_NOTICE
                body = body.replace(b'</body>', notice + b'</body>', 1)
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
        if scope['type']=='http' and scope['method']=='GET' and scope['path']=='/api/status':
            import json
            pending=[]
            async def capture(message):pending.append(message)
            await self.app(scope,receive,capture)
            start=next((m for m in pending if m['type']=='http.response.start'),None)
            headers=dict(start.get('headers',[])) if start else {}
            if start and start['status']==200 and b'application/json' in headers.get(b'content-type',b'') and b'content-encoding' not in headers:
                body=b''.join(m.get('body',b'') for m in pending if m['type']=='http.response.body')
                value=json.loads(body)
                value['can_update_hermes']=False
                value['fabriquinha_observation_only']=True
                body=json.dumps(value).encode()
                await send(dict(start,headers=[(k,v) for k,v in start['headers'] if k.lower()!=b'content-length']+[(b'content-length',str(len(body)).encode())]))
                await send({'type':'http.response.body','body':body});return
            for message in pending:await send(message)
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
    app.add_middleware(KanbanGuidance, root=root)
    app.add_middleware(ObservationOnly)
    start_server(host='127.0.0.1', port=args.port, open_browser=False, isolated=True)


if __name__ == '__main__':
    main()
