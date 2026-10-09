import json,sqlite3,tempfile,threading,unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from broker import technical_remediation_plan as module


class PlanLengthRecoveryTests(unittest.TestCase):
    def test_capture_binds_durable_receipt_without_dispatch_or_approval(self):
        from broker import execution_diagnosis_recovery as receipts
        c=sqlite3.connect(':memory:');self.addCleanup(c.close);c.row_factory=sqlite3.Row
        module.initialize(c);c.executescript('CREATE TABLE leases(request_id,status);CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id);')
        c.execute("INSERT INTO leases VALUES('req','closed')")
        c.execute("INSERT INTO native_bindings VALUES('req','task','cto','issue')")
        config=dict(cto='cto',intake_kind='rejected_remediation_r1_v1',required_paths=['/evidence/candidate/test.py'])
        state=dict(stage='blocked',category='ValueError',issue_id='issue',wakeup_id='wake',execution_authorized=False)
        c.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',('source',json.dumps(config),json.dumps(state)))
        @contextmanager
        def db():yield c
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),PREFIX='delivery-kit-test',docker=lambda *a:dict(Image='sha256:image'))
        task=dict(id='task',status='failed',agent_id='cto',issue_id='issue',wakeup_id='wake')
        fx=SimpleNamespace(settings={},task=lambda *a:task,reads=lambda t:{config['required_paths'][0]:dict(lines=2,total_lines=2)})
        rejection=dict(operation='rejected_typed_decision_adapter_v1',category='typed_schema_maxLength',delivery_approval=False,worker_tool_executed=False)
        with patch.object(module,'Effects',return_value=fx),patch.object(module.native,'issue_task_runs',return_value=[task]),patch.object(receipts,'format_rejection',return_value=rejection) as query:
            diagnosis=module.capture_plan_length_failure(b,'source')
            self.assertEqual(diagnosis['rejection']['execution_id'],'req')
            self.assertFalse(diagnosis['retry_authorized'])
            self.assertEqual(module.capture_plan_length_failure(b,'source'),diagnosis)
            self.assertEqual(query.call_count,1)
        stored=json.loads(c.execute('SELECT state FROM technical_remediation_plans').fetchone()[0])
        self.assertEqual(stored['stage'],'blocked');self.assertFalse(stored['execution_authorized'])

    def test_one_correlated_recovery_preserves_failed_state_and_does_not_approve_plan(self):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close);c.row_factory=sqlite3.Row
        module.initialize(c);c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT)')
        c.execute("INSERT INTO leases VALUES('req','closed')")
        c.execute("INSERT INTO native_bindings VALUES('req','old-plan','cto','issue')")
        config=dict(cto='cto',reviewer='lead',amendment={'operation':'inherited_harness_contract_amendment_v1'},
            required_paths=['/evidence/candidate/test_new.py'])
        state=dict(stage='blocked',category='ValueError',owner='cto',issue_id='issue',wakeup_id='old-wake',
            execution_authorized=False,format_diagnosis=dict(category='typed_schema_maxLength',request_id='req',
                failed_task='old-plan',retry_authorized=False))
        c.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',('source',json.dumps(config),json.dumps(state)))
        rejection=dict(execution_id='req',operation='rejected_typed_decision_adapter_v1',category='typed_schema_maxLength',
            delivery_approval=False,worker_tool_executed=False,response_shape=dict(parsed=True,terminal=True,submissions=1,
                expected_tool=True,arguments_json_valid=True,arguments_schema_valid=False,content_shape='empty',content_chars=0))
        task=dict(status='failed',issue_id='issue',wakeup_id='old-wake')
        fx=SimpleNamespace(task=lambda *a:task,reads=lambda t:{config['required_paths'][0]:dict(lines=10,total_lines=10)},settings={})
        @contextmanager
        def db():yield c
        b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with patch.object(module,'Effects',return_value=fx),patch.object(module.native,'issue_task_runs',return_value=[]),patch.object(module,'instruction',return_value='\nDELIVERY_REMEDIATION_PLAN_LENGTH_FEEDBACK_V1\n'):
            with self.assertRaises(ValueError):module.reconcile_plan_length_failure(b,'source',{**rejection,'execution_id':'foreign'})
            new=module.reconcile_plan_length_failure(b,'source',rejection)
            self.assertEqual(new['stage'],'plan_dispatch');self.assertNotIn('wakeup_id',new)
            self.assertEqual(new['plan_length_recovery']['previous'],state)
            self.assertFalse(new['plan_length_recovery']['implementation_authorized'])
            self.assertFalse(new['plan_length_recovery']['limits_increased'])
            self.assertEqual(module.reconcile_plan_length_failure(b,'source',rejection),new)
        self.assertEqual(c.execute('SELECT count(*) FROM technical_remediation_plans').fetchone()[0],1)
