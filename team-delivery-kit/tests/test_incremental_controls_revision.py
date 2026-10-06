import copy
import contextlib
import json
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_incremental_seed_transport as fixtures
from broker import incremental_checkpoints as ledger,incremental_controls_revision as runtime


class ControlsRevisionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.SeedTransportRevisionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.con=f.con;f.prepare()
        state=ledger.status(self.con,'source');state['units']['U1']['binding']={'issue_id':'revision4'}
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        self.before=copy.deepcopy(state)
        self.receipt=dict(operation='cto_negative_controls_revision_v1',source_task='source',unit='U1',
            parent_issue='revision4',decision_task='controls-cto',cto='cto',proposal_sha256='a'*64,
            reason='Add actual negative-control methods',experiment_sha256='9'*64,fixture_volume='owned-fixture',
            diagnosis_sha256='8'*64,rejected_manifest_sha256='7'*64)

    def prepare(self,receipt=None):
        r=self.receipt if receipt is None else receipt
        return ledger.prepare_controls_revision(self.con,'source',ledger.digest(r),lambda _:r)

    def test_one_revision_preserves_history_base_and_dependency(self):
        state=self.prepare();u=state['units']['U1']
        self.assertEqual(u['revision'],5);self.assertEqual(len(u['history']),4)
        self.assertFalse(state['execution_authorized']);self.assertEqual(state,self.prepare())
        self.assertEqual(state['units']['U2'],self.before['units']['U2'])
        for key in ('base_manifest_sha256','baseline_test_sha256','prior_test_count'):
            self.assertEqual(u[key],self.before['units']['U1'][key])
        for key in ('binding','red','test_review','green'):self.assertNotIn(key,u)

    def test_wrong_parent_owner_proof_and_lineage_do_not_reset(self):
        for key,value in [('parent_issue','other'),('cto','author'),('unit','U2'),
                          ('diagnosis_sha256','invalid'),('experiment_sha256','0'*64),('fixture_volume','other')]:
            with self.assertRaises(ValueError):self.prepare({**self.receipt,key:value})
        self.assertEqual(ledger.status(self.con,'source'),self.before)

    def test_checkpointed_red_cannot_be_discarded(self):
        state=copy.deepcopy(self.before);state['units']['U1']['red']='0'*64
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):self.prepare()


class ControlsRuntimeTests(unittest.TestCase):
    def setUp(self):
        f=ControlsRevisionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.con=f.con;self.con.row_factory=sqlite3.Row
        for sql in ['CREATE TABLE leases(status TEXT)',
            'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)',
            'CREATE TABLE incremental_runtime_incidents(source_task TEXT PRIMARY KEY,receipt TEXT)',
            'CREATE TABLE incremental_runtime_incident_archive(source_task TEXT,revision INT,receipt TEXT,PRIMARY KEY(source_task,revision))',
            'CREATE TABLE incremental_controls_replans(source_task TEXT,revision INT,config TEXT,state TEXT)',
            'CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)',
            'CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)',
            'CREATE TABLE delivery_handoffs(source_task TEXT PRIMARY KEY,issue_id TEXT,stage TEXT,owner TEXT,data TEXT,updated REAL)',
            'CREATE TABLE delivery_handoff_events(source_task TEXT,stage TEXT,data TEXT,at REAL)']:
            self.con.execute(sql)
        self.decision=dict(action='request_test_revision',reason='Add genuine controls',optional_files=[])
        self.task=dict(id='cto-native',status='completed',issue_id='revision4',wakeup_id='wake')
        self.proof=dict(operation='immutable_candidate_missing_controls_diagnosis_v1',revision=4,
            task_id='author',manifest_sha256='7'*64,test_sha256={'tests/new.py':'6'*64},new_test_methods=2,old_test_methods=2)
        self.incident=dict(category='new_negative_control_tests_missing',owner='cto',diagnosis=self.proof,diagnosis_sha256=ledger.digest(self.proof))
        self.route=dict(enabled=False,cto='cto',test_first_files=['tests/new.py'])
        trial=dict(harness_selector_experiment={'input_sha256':{'tests/new.py':'5'*64}},harness_fixture_volume='owned-fixture')
        red=dict(task_id='author',red=dict(manifest_sha256='7'*64,test_sha256=self.proof['test_sha256']))
        result=dict(terminal_recovery=dict(stage='sponsored',task_id='cto-native',wakeup_id='wake',decision=self.decision))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('revision4',json.dumps(self.route)))
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('source',json.dumps(self.incident)))
        self.con.execute('INSERT INTO incremental_controls_replans VALUES(?,?,?,?)',('source',4,json.dumps(dict(issue_id='revision4',cto='cto',proof=self.proof)),json.dumps(result)))
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('revision4',json.dumps(trial)))
        self.con.execute('INSERT INTO test_first_red VALUES(?,?)',('revision4',json.dumps(red)))
        class State:
            def __truediv__(self,name):return SimpleNamespace(read_text=lambda:'{}')
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=self.db,STATE=State())

    @contextlib.contextmanager
    def db(self):yield self.con

    def prepare(self):
        with patch.object(runtime.native,'task_record',return_value=self.task), \
             patch.object(runtime.native,'issue_task_runs',return_value=[]), \
             patch.object(runtime.handoff_runtime,'Effects') as effects:
            effects.return_value.decision.return_value=self.decision
            return runtime.prepare(self.b,'source')

    def test_real_decision_archives_incident_and_preserves_seed_evidence(self):
        receipt=self.prepare();self.assertEqual(receipt,self.prepare())
        self.assertEqual(ledger.status(self.con,'source')['units']['U1']['revision'],5)
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incident_archive').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],0)
        data=json.loads(self.con.execute('SELECT data FROM delivery_handoffs').fetchone()[0])
        self.assertEqual(data['controls_completion'],self.proof)
        self.assertFalse(ledger.status(self.con,'source')['execution_authorized'])

    def test_stale_failed_or_wrong_issue_decision_rejected(self):
        for key,value in [('status','failed'),('issue_id','other'),('wakeup_id','other')]:
            before=dict(self.task);self.task[key]=value
            with self.assertRaises(ValueError):self.prepare()
            self.task=before
        self.assertEqual(ledger.status(self.con,'source')['units']['U1']['revision'],4)

    def test_rejected_seed_hash_drift_rejected(self):
        red=dict(task_id='author',red=dict(manifest_sha256='0'*64,test_sha256=self.proof['test_sha256']))
        self.con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(red),))
        with self.assertRaises(ValueError):self.prepare()

    def test_handoff_conflict_rolls_back_revision_and_archive(self):
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?,?)',('cto-native','other','old','cto','{}',1))
        with self.assertRaises(sqlite3.IntegrityError):self.prepare()
        self.assertEqual(ledger.status(self.con,'source')['units']['U1']['revision'],4)
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],1)
