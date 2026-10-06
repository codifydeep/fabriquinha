import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from coordination_store import CoordinationStore
import host_recovery as h

class RecoveryTests(unittest.TestCase):
    def test_new_proof_requeues_once_and_never_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'e2e.json').write_text(json.dumps(dict(attempt='test',cards=dict(deploy='d'))))
            store=CoordinationStore(root/'coord.db'); store.create_attempt('test','test','test')
            db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
            db.executescript("CREATE TABLE tasks(id,status,current_run_id); INSERT INTO tasks VALUES('d','blocked',NULL); CREATE TABLE task_events(id,task_id,kind,payload);")
            reason=dict(category='host_receipt_pending',expected_commit='sha',at=100)
            db.execute('INSERT INTO task_events VALUES(1,?,?,?)',('d','blocked',json.dumps(dict(reason=json.dumps(reason)))))
            config=dict(attempt='test',db_path=root/'kanban.db')
            with patch.object(h,'readiness',return_value=dict(ready=True,commit='sha',receipt_at=101)),patch.object(h,'cli') as cli:
                self.assertTrue(h.tick(db,config,store,102)); self.assertFalse(h.tick(db,config,store,103))
                self.assertEqual(cli.call_args.args[1:3],('unblock','d')); self.assertEqual(cli.call_count,1)
            store.close(); db.close()
