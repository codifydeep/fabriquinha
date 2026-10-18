import copy
import hashlib
import unittest
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
from broker import literal_plan_preflight_recovery as recovery
from broker import literal_maintenance_workflow as flow
from broker import literal_maintenance_effects as lane
import recover_literal_plan_preflight as cli


class PlanRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(source=dict(author_task='source'),author='author',cto='cto',reviewer='lead',
            test_path='tests/test.py',literal='NODE_HARNESS')
        self.state=dict(stage='blocked',category='native_plan_failed',issue_id='child',marker='old',wakeup_id='wake',
            decisions={'triage':{}},revision=0,history=[],source_reset=False,functional_red=False,delivery_approval=False)
        note=lane.expected_note(self.cfg,self.state,'plan').replace('DELIVERY_TYPED_DECISION_V1\n',
            'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\n',1)
        self.task=dict(id='failed',status='failed',error=recovery.ERROR,agent_id='cto',issue_id='child',
            wakeup_id='wake',handoff_note=note)
        self.binding=dict(status='closed',task_id='failed',scope='owned:planning:failed',agent_id='cto',issue_id='child',
            request_id='11111111-1111-4111-8111-111111111111',tool_count=0)
        self.proof=dict(calls_before=6121,calls_after=6121,policy_sha256=flow.preflight_plan(self.cfg,self.state),
            rejections=[dict(operation='local_request_rejection_v1',execution_id=self.binding['request_id'],
                request_sha256='a'*64,stage='contract',origin=dict(module='typed_decision_contract',line=467),
                exception_type='ValueError',error_sha256=hashlib.sha256(b'observed non-approving test diagnosis contract required').hexdigest(),
                retry_authorized=False,delivery_approval=False)])

    def qualify(self,**changes):
        return recovery.qualify(changes.get('cfg',self.cfg),changes.get('state',self.state),changes.get('task',self.task),
            changes.get('binding',self.binding),changes.get('proof',self.proof))

    def test_only_local_closed_no_tools_failure_can_qualify_new_plan_without_source_reset(self):
        receipt=self.qualify();self.assertEqual(receipt['attempt_limit'],1)
        self.assertEqual(receipt['previous_state'],self.state)
        for flag in ('author_retry_authorized','source_reset','execution_authorized','delivery_approval'):
            self.assertFalse(receipt[flag])

    def test_foreign_task_wakeup_scope_or_generic_provider_error_is_not_enough(self):
        for change in (dict(agent_id='author'),dict(wakeup_id='other'),dict(status='completed'),dict(error='other'),
                dict(handoff_note='prefix '+self.task['handoff_note'])):
            with self.assertRaises(ValueError):self.qualify(task={**self.task,**change})
        for change in (dict(status='running'),dict(scope='owned:implementation:failed'),dict(tool_count=1)):
            with self.assertRaises(ValueError):self.qualify(binding={**self.binding,**change})

    def test_paid_or_different_or_missing_rejection_cannot_rearm_planner(self):
        for change in (dict(calls_after=6122),dict(rejections=[]),dict(policy_sha256='b'*64)):
            with self.assertRaises(ValueError):self.qualify(proof={**self.proof,**change})
        for change in (dict(stage='upstream'),dict(execution_id='22222222-2222-4222-8222-222222222222'),
                dict(error_sha256='b'*64)):
            proof=copy.deepcopy(self.proof);proof['rejections'][0].update(change)
            with self.assertRaises(ValueError):self.qualify(proof=proof)

    def test_repeated_recovery_or_author_start_or_existing_approval_is_refused(self):
        for change in (dict(preflight_recovery='already-used'),dict(author_task='author-task'),
                dict(prepared={'base':'existing'}),dict(delivery_approval=True),dict(revision=1)):
            with self.assertRaises(ValueError):self.qualify(state={**self.state,**change})

    def test_fixed_embedded_programs_compile_and_never_use_upstream_http(self):
        for script in (recovery.PROBE,cli.PROGRAM):compile(script,'fixed-probe','exec')
        self.assertNotIn('urlopen',recovery.PROBE);self.assertNotIn('requests.',recovery.PROBE)

    def database(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        flow.initialize(con)
        con.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',
            ('source',json.dumps(self.cfg),json.dumps(self.state)))
        con.execute('CREATE TABLE native_bindings(request_id,task_id,scope,agent_id,issue_id)')
        con.execute('CREATE TABLE leases(request_id,status)')
        con.execute('CREATE TABLE tool_events(request_id,tool_count)')
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',tuple(self.binding[k] for k in
            ('request_id','task_id','scope','agent_id','issue_id')))
        con.execute('INSERT INTO leases VALUES(?,?)',(self.binding['request_id'],'closed'));con.commit()
        return con

    def test_register_preserves_failed_state_and_is_idempotent_without_second_proxy_read(self):
        con=self.database();b=SimpleNamespace(LOCK=threading.RLock(),db=lambda:con)
        fx=Mock();fx.plans.task.return_value=self.task;fx.old.proxy_read.return_value=(self.proof,'sha256:proxy')
        seal=dict(stage='sealed',operation_id='maintenance')
        with patch.object(recovery.maintenance,'current',return_value=seal),\
                patch.object(recovery.maintenance,'native_active',return_value=[]),\
                patch.object(recovery.lane,'Effects',return_value=fx),patch.object(recovery.flow,'authenticate'):
            receipt=recovery.register(b,'source','failed')
            state=json.loads(con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()[0])
            self.assertEqual(state['stage'],'plan_dispatch');self.assertEqual(state['decisions'],self.state['decisions'])
            self.assertEqual(receipt['previous_state'],self.state)
            self.assertEqual(recovery.register(b,'source','failed'),receipt)
            with self.assertRaises(ValueError):recovery.register(b,'source','another-failed-task')
        fx.old.proxy_read.assert_called_once();fx.plans.task.assert_called_once()
        self.assertEqual(con.execute('SELECT count(*) FROM literal_plan_schema_recoveries').fetchone()[0],1)

    def test_unsealed_or_active_worker_cannot_register_recovery(self):
        con=self.database();b=SimpleNamespace(LOCK=threading.RLock(),db=lambda:con)
        with patch.object(recovery.maintenance,'current',return_value=None):
            with self.assertRaises(ValueError):recovery.register(b,'source','failed')
        con.execute('UPDATE leases SET status="running"')
        with patch.object(recovery.maintenance,'current',return_value=dict(stage='sealed')):
            with self.assertRaises(ValueError):recovery.register(b,'source','failed')
