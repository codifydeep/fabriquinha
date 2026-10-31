import asyncio
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dashboard_launcher', Path(__file__).parents[2] / 'scripts/run_hermes_dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ObservationTests(unittest.TestCase):
    def test_guidance_preserves_auth_errors_and_api_payloads(self):
        for path, status, content in [('/kanban', 401, b'text/html'), ('/api/status', 200, b'application/json'), ('/kanban', 200, b'text/html')]:
            output = []
            async def inner(scope, receive, send):
                await send({'type':'http.response.start', 'status':status, 'headers':[(b'content-type',content)]})
                await send({'type':'http.response.body', 'body':b'<body>native</body>'})
            async def send(message):
                output.append(message)
            asyncio.run(module.KanbanGuidance(inner)({'type':'http','method':'GET','path':path}, None, send))
            self.assertEqual(output[0]['status'], status)
            self.assertEqual(module.KANBAN_NOTICE in output[1]['body'], path == '/kanban' and status == 200)

    def invoke(self, scope):
        messages, reached = [], []
        async def inner(scope, receive, send):
            reached.append(True)
        async def send(message):
            messages.append(message)
        async def receive():
            return {'type': 'http.disconnect'}
        asyncio.run(module.ObservationOnly(inner)(scope, receive, send))
        return messages, reached

    def test_read_board_allowed(self):
        self.assertTrue(self.invoke({'type': 'http', 'method': 'GET', 'path': '/api/plugins/kanban/board'})[1])

    def test_mutations_never_reach_native_handlers(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            messages, reached = self.invoke({'type': 'http', 'method': method, 'path': '/api/plugins/kanban/tasks'})
            self.assertFalse(reached)
            self.assertEqual(messages[0]['status'], 403)

    def test_chat_and_terminal_websocket_denied(self):
        for path in ('/api/chat', '/api/pty', '/api/plugins/kanban/events/other'):
            messages, reached = self.invoke({'type': 'websocket', 'path': path})
            self.assertFalse(reached)
            self.assertEqual(messages[0]['code'], 1008)

    def test_kanban_event_stream_allowed(self):
        self.assertTrue(self.invoke({'type': 'websocket', 'path': '/api/plugins/kanban/events'})[1])


class SummaryTests(unittest.TestCase):
    def test_stale_or_missing_state_never_reports_success(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            self.assertIn('indisponível',module.operational_summary(root,now=100))
            (root/'status.json').write_text(json.dumps({'observed_at':0}))
            self.assertIn('desatualizada',module.operational_summary(root,now=100))

    def test_raw_done_is_not_acceptance_and_titles_are_escaped(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            status=dict(observed_at=99,dispatcher_state='running',board=dict(cards=[dict(
                id='t_one',kind='release',created_at=1,status='done',title='<script>bad</script>')]))
            (root/'status.json').write_text(json.dumps(status))
            view=module.operational_summary(root,now=100)
            self.assertIn('sem recibo',view)
            self.assertNotIn('<script>',view)
            self.assertNotIn('HOMOLOGADA',view)

    def test_exact_acceptance_is_shown_without_promoting_autonomy(self):
        import tempfile,json,hashlib
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);folder=root/'private/receipts';folder.mkdir(parents=True)
            status=dict(observed_at=99,dispatcher_state='running',board=dict(cards=[dict(
                id='t_one',kind='release',created_at=1,status='done',title='Release')]))
            (root/'status.json').write_text(json.dumps(status))
            receipt=dict(kind='release_acceptance',binding=dict(task='t_one',actor='controller'),
                payload=dict(state='HOMOLOGADA',assisted=True,commit='sha',url='http://localhost'))
            raw=json.dumps(receipt,sort_keys=True,separators=(',',':')).encode()
            path=folder/(hashlib.sha256(raw).hexdigest()+'.json');path.write_bytes(raw)
            view=module.operational_summary(root,now=100)
            self.assertIn('HOMOLOGADA',view);self.assertIn('assistido',view)
            path.write_text('{}')
            self.assertNotIn('HOMOLOGADA',module.operational_summary(root,now=100))
