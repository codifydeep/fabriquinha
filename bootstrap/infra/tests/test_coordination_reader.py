import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore
from coordination_reader import read_receipts

class ReaderTests(unittest.TestCase):
    def test_closed_wal_without_sidecars_and_fresh_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'coordination.db'; attempt='test'
            s=CoordinationStore(p); s.create_attempt(attempt,'board','v1'); s.close()
            self.assertFalse(Path(str(p)+'-wal').exists())
            req=dict(operation='recovery_receipts',attempt=attempt)
            self.assertIsNone(read_receipts(p,attempt,req)['fault'])
            s=CoordinationStore(p)
            with s.transaction(attempt): s._put(attempt,'e2e_fault','green-worker-interruption',dict(state='intent'))
            self.assertEqual(read_receipts(p,attempt,req)['fault']['state'],'intent')
            s.close()
            self.assertEqual(read_receipts(p,attempt,req)['fault']['state'],'intent')
            for bad in [dict(operation='delete',attempt=attempt),dict(req,sql='DELETE FROM records'),dict(req,attempt='other')]:
                with self.assertRaises(PermissionError): read_receipts(p,attempt,bad)
