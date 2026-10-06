import json,tempfile,unittest
from pathlib import Path
from coordination_store import CoordinationStore
from product_notifications import ATTEMPT,flush

class NotificationTests(unittest.TestCase):
    def test_failure_retains_queue_success_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=CoordinationStore(Path(tmp)/'ledger.db')
            try:
                store.create_attempt(ATTEMPT,'trial','v0')
                store.enqueue(ATTEMPT,'one',json.dumps(dict(attempt=ATTEMPT,profile='backend_data',event='activity_started',task='t_one',run=1,mode='implementation')))
                def fail(*args):raise ConnectionError('offline')
                with self.assertRaises(ConnectionError):flush(store,'fixed',lambda p:'token',fail)
                self.assertEqual(len(store.pending(ATTEMPT)),1)
                sent=[]
                self.assertEqual(flush(store,'fixed',lambda p:'token',lambda *a:sent.append(a)),1)
                self.assertEqual(flush(store,'fixed',lambda p:'token',lambda *a:sent.append(a)),0)
                self.assertEqual(len(sent),1)
            finally:store.close()
