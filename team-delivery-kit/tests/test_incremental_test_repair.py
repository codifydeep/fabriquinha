"""Controller adapter fixtures, not evidence of autonomous delivery."""
import contextlib
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_incremental_checkpoints as fixtures
from broker import incremental_test_repair as repair


class TestRepairAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IncrementalCheckpointTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.con = self.fixture.con
        self.state = self.fixture.state
        self.receipt = self.fixture.repair_receipt()
        self.con.execute('CREATE TABLE leases(status TEXT)')
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        self.con.execute('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,data TEXT,updated REAL)')
        self.decision = dict(action='request_test_revision', reason=self.receipt['reason'], optional_files=[])
        self.route = dict(enabled=True, cto='cto', test_first_files=['tests/new_U1.py'])
        self.data = dict(target='cto', wakeup_id='wake', decision=self.decision,
            validation_failure=dict(category='executed_test_failure', output_sha256='9'*64),
            test_revision_proposal=dict(decision_task='diagnosis', source_task='failed-author',
                reason=self.receipt['reason'], output_sha256='9'*64, new_test_files=['tests/new_U1.py']))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)', ('old-unit',json.dumps(self.route)))
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?)',
            ('failed-author','old-unit','test_revision_required',json.dumps(self.data),1))
        self.b = SimpleNamespace(LOCK=threading.RLock(), db=self.db,
            STATE=SimpleNamespace(__truediv__=lambda self, name: None))
        # Path-like fixture without secrets or network.
        class State:
            def __truediv__(self, name):
                return SimpleNamespace(read_text=lambda:'{}')
        self.b.STATE = State()
        self.task = dict(id='diagnosis', status='completed', issue_id='old-unit', wakeup_id='wake')

    @contextlib.contextmanager
    def db(self):
        yield self.con

    def prepare(self):
        with patch.object(repair.native,'task_record',return_value=self.task), \
             patch.object(repair.handoff_runtime,'Effects') as effects:
            effects.return_value.decision.return_value = self.decision
            return repair.prepare(self.b,'source')

    def test_runtime_verifies_diagnosis_and_pauses_original_route(self):
        self.assertEqual(self.prepare(), self.receipt)
        route = json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0])
        self.assertFalse(route['enabled'])
        self.assertEqual(self.state()['units']['U1']['revision'],2)
        self.assertEqual(self.prepare(),self.receipt)

    def test_wrong_native_execution_rejected_without_transition(self):
        for key,value in [('status','failed'),('issue_id','other'),('wakeup_id','other')]:
            original = dict(self.task); self.task[key] = value
            with self.assertRaises(ValueError): self.prepare()
            self.task = original
        self.assertEqual(self.state()['units']['U1']['revision'],1)

    def test_running_worker_prevents_repair(self):
        self.con.execute("INSERT INTO leases VALUES('running')")
        with self.assertRaises(ValueError):self.prepare()

    def test_changed_failure_evidence_rejected(self):
        self.data['validation_failure']['output_sha256']='0'*64
        self.con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(self.data),))
        with self.assertRaises(ValueError):self.prepare()

    def test_dependent_repair_requires_actual_reads_and_preserves_base(self):
        config,state=map(json.loads,self.con.execute('SELECT config,state FROM incremental_checkpoints').fetchone())
        candidate=dict(state['units']['U1']);candidate['id']='U3'
        state['units']['U3']=candidate
        state['units']['U2'].update(stage='checkpointed',green_manifest_sha256=candidate['base_manifest_sha256'])
        config['units'].append(dict(id='U3',depends_on=['U2'],criteria=['C03'],objective='Third'))
        self.con.execute('UPDATE incremental_checkpoints SET config=?,state=?',(json.dumps(config),json.dumps(state)))
        self.data['validation_failure']['diagnostic_read_files']=['app/static/app.js']
        self.con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(self.data),))
        with patch.object(repair.native,'task_record',return_value=self.task), patch.object(repair.handoff_runtime,'Effects') as effects:
            effects.return_value.decision.return_value=self.decision
            effects.return_value.read_evidence.return_value=['/evidence/candidate/tests/new_U1.py']
            with self.assertRaisesRegex(ValueError,'observed repair sponsorship'):
                repair.prepare(self.b,'source','U3')
            self.assertEqual(self.state()['units']['U3']['revision'],1)
            effects.return_value.read_evidence.return_value=['/evidence/candidate/tests/new_U1.py','/evidence/candidate/app/static/app.js']
            result=repair.prepare(self.b,'source','U3')
        self.assertEqual(result['unit'],'U3')
        self.assertEqual(self.state()['units']['U3']['base_manifest_sha256'],candidate['base_manifest_sha256'])
