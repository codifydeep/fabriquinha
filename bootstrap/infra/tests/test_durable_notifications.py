from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore
from durable_notifications import enqueue, flush


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'store.db'
        self.store = CoordinationStore(self.path)
        self.addCleanup(self.store.close)
        self.store.create_attempt('r2', 'b2', 'v0.1')
        self.config = dict(attempt='r2', coordination_path=self.path, chat_id='test-only')

    def test_outage_retains_message_and_retry_delivers_once(self):
        enqueue(self.config, 'techlead', 'started', 'event:1')
        enqueue(self.config, 'techlead', 'started', 'event:1')
        def fail(*args):
            raise TimeoutError('network unavailable')
        self.assertEqual(flush(self.config, fail, lambda _: 'secret'), 0)
        self.assertEqual(len(self.store.pending('r2')), 1)
        received = []
        self.assertEqual(flush(self.config, lambda *args: received.append(args), lambda _: 'secret'), 1)
        self.assertEqual(flush(self.config, lambda *args: received.append(args), lambda _: 'secret'), 0)
        self.assertEqual(len(received), 1)
        self.assertNotIn('secret', str(self.store.db.execute('SELECT * FROM outbox').fetchall()[0]['text']))

    def test_old_attempt_cannot_enqueue(self):
        self.config['attempt'] = 'r1'
        with self.assertRaises(ValueError):
            enqueue(self.config, 'techlead', 'started', 'event:1')
