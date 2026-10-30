import asyncio
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dashboard_launcher', Path(__file__).parents[2] / 'scripts/run_hermes_dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ObservationTests(unittest.TestCase):
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
