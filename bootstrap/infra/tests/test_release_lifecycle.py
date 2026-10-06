from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore
from delivery_receipts import EvidenceStore
from release_lifecycle import finalize


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=CoordinationStore(self.root/'coordination.db')
        self.addCleanup(self.store.close)
        self.store.create_attempt('r2','b2','v0.1')
        self.store.transition('r2','EM_DESCOBERTA','AGUARDANDO_APROVACAO_DO_BRIEF','produto',{'brief':'fixture'})
        self.store.transition('r2','AGUARDANDO_APROVACAO_DO_BRIEF','ATIVA','ceo',{'brief_sha256':'a'*64,'criteria':['lobby']})
        self.store.transition('r2','ATIVA','EM_HOMOLOGACAO','techlead',{'deployment':'fixture'})
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,status TEXT)')
        self.db.execute("INSERT INTO tasks VALUES('release','done')")
        self.registry=dict(attempt='r2',board='b2',controller='release',branch='release/v0.1',approved_criteria=['lobby'])
        self.config=dict(attempt='r2',board='b2',chat_id='fixture')
        evidence=EvidenceStore(self.root/'evidence','r2')
        blob=evidence.capture_bytes('qa.log',b'passed')
        self.digest=evidence.save(dict(kind='homologation',task='release',criteria=['lobby'],
            commit='a'*40,report=dict(commit='a'*40,url='http://localhost:8080'),artifacts=[blob]))
        with self.store.transaction('r2'):
            self.store._put('r2','delivery_receipt','release',dict(kind='homologation',sha256=self.digest))
            self.store._put('r2','verified_receipt',self.digest,dict(kind='homologation',task='release'))

    def finish(self):
        return finalize(self.db,self.config,self.store,self.registry,self.root/'evidence')

    def test_complete_once_and_final_notification_survives_terminal(self):
        self.assertTrue(self.finish())
        self.assertFalse(self.finish())
        pending=self.store.pending('r2')
        self.assertEqual(len(pending),1)
        self.store.sent('r2',pending[0]['id'])
        self.assertEqual(self.store.pending('r2'),[])

    def test_running_controller_is_not_complete(self):
        self.db.execute("UPDATE tasks SET status='running'")
        self.assertFalse(self.finish())

    def test_remaining_blocked_card_prevents_completion(self):
        self.db.execute("INSERT INTO tasks VALUES('other','blocked')")
        self.assertFalse(self.finish())

    def test_explicit_release_scope_ignores_historical_incident(self):
        self.registry['mandatory_tasks']=['release']
        self.db.execute("INSERT INTO tasks VALUES('old-incident','blocked')")
        self.assertTrue(self.finish())

    def test_mandatory_missing_or_archived_cannot_count_as_delivered(self):
        self.registry['mandatory_tasks']=['release','implementation']
        self.assertFalse(self.finish())
        self.db.execute("INSERT INTO tasks VALUES('implementation','archived')")
        self.assertFalse(self.finish())

    def test_empty_release_scope_rejected(self):
        self.registry['mandatory_tasks']=[]
        with self.assertRaises(ValueError):self.finish()

    def test_missing_receipt_bytes_prevent_completion(self):
        (self.root/'evidence'/'r2'/'receipts'/self.digest).unlink()
        with self.assertRaises(FileNotFoundError):
            self.finish()
        self.assertEqual(self.store.pending('r2'),[])

    def test_notification_conflict_rolls_back_terminal_transition(self):
        self.store.enqueue('r2','release:homologated','conflicting fixture')
        with self.assertRaises(ValueError):
            self.finish()
        self.assertEqual(self.store.db.execute("SELECT state FROM attempts WHERE id='r2'").fetchone()[0],'EM_HOMOLOGACAO')
