import contextlib
import json
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_incremental_harness_revision as ledger_fixtures
import test_incremental_harness_replan as proof_fixtures
from broker import incremental_harness_replan as replan, incremental_checkpoints as ledger


class HarnessRuntimeTests(unittest.TestCase):
    def setUp(self):
        f=ledger_fixtures.HarnessRevisionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.con=f.con;self.con.row_factory=sqlite3.Row
        for sql in ['CREATE TABLE leases(status TEXT)',
            'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)',
            'CREATE TABLE incremental_runtime_incidents(source_task TEXT PRIMARY KEY,receipt TEXT)',
            'CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)',
            'CREATE TABLE delivery_handoffs(source_task TEXT PRIMARY KEY,issue_id TEXT,stage TEXT,owner TEXT,data TEXT,updated REAL)',
            'CREATE TABLE delivery_handoff_events(source_task TEXT,stage TEXT,data TEXT,at REAL)']:
            self.con.execute(sql)
        replan.initialize(self.con)
        proof=proof_fixtures.HarnessReplanTests();proof.setUp();self.proof=proof.proof
        sha=ledger.digest(self.proof)
        self.decision=dict(action='request_test_revision',reason='Repair real attribute matching',optional_files=[])
        result=dict(stage='sponsored',task_id='cto-native',wakeup_id='wake',decision=self.decision,experiment_sha256=sha)
        plan=dict(issue_id='repair2',revision=2,cto='cto',experiment=self.proof)
        self.con.execute('INSERT INTO incremental_harness_replans VALUES(?,?,?)',('source',json.dumps(plan),json.dumps(result)))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('repair2',json.dumps(dict(enabled=False,cto='cto',test_first_files=['tests/test_feedback_search_client.py']))))
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('source',json.dumps(dict(category='unchanged_seed_after_sponsored_repair',harness_experiment_sha256=sha))))
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('repair2',json.dumps(dict(old_red={'red':{'test_sha256':self.proof['input_sha256']}}))))
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?,?)',('failed-author','repair2','failed','cto','{}',1))
        class State:
            def __truediv__(self,name):return SimpleNamespace(read_text=lambda:'{}')
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=self.db,STATE=State(),OWNER='owner',
            docker=lambda *args: {'Labels':{'delivery-kit.owner':'owner'}})
        self.task=dict(id='cto-native',status='completed',issue_id='repair2',wakeup_id='wake')

    @contextlib.contextmanager
    def db(self):yield self.con

    def prepare(self):
        with patch.object(replan.native,'task_record',return_value=self.task), \
             patch.object(replan.native,'issue_task_runs',return_value=[]), \
             patch.object(replan.handoff_runtime,'Effects') as effects:
            effects.return_value.decision.return_value=self.decision
            return replan.prepare_revision(self.b,'source','owned-fixture')

    def test_real_sponsor_creates_separate_handoff_and_archives_incident(self):
        receipt=self.prepare()
        self.assertEqual(receipt,self.prepare())
        state=ledger.status(self.con,'source')
        self.assertEqual(state['units']['U1']['revision'],3)
        self.assertFalse(state['execution_authorized'])
        self.assertEqual(self.con.execute("SELECT stage FROM delivery_handoffs WHERE source_task='failed-author'").fetchone()[0],'failed')
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incident_archive').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],0)

    def test_stale_failed_or_other_native_decision_cannot_start_revision(self):
        for key,value in [('status','failed'),('issue_id','other'),('wakeup_id','other')]:
            before=dict(self.task);self.task[key]=value
            with self.assertRaises(ValueError):self.prepare()
            self.task=before
        self.assertEqual(ledger.status(self.con,'source')['units']['U1']['revision'],2)

    def test_handoff_conflict_rolls_back_ledger_and_incident_archive(self):
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?,?)',('cto-native','other','old','cto','{}',1))
        with self.assertRaises(sqlite3.IntegrityError):self.prepare()
        self.assertEqual(ledger.status(self.con,'source')['units']['U1']['revision'],2)
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],1)
