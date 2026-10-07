import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock,patch
from broker import remediation_admission as admission


class RemediationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        @contextmanager
        def db():yield self.con;self.con.commit()
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=db)
        self.con.execute('CREATE TABLE remediation_executions(source_task TEXT,contract TEXT,state TEXT)')
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        self.plan={'approved':'all criteria'};self.value=dict(root_issue='root',original_depth=2,plan_sha256=admission.planning.digest(self.plan))
        self.parent={'execution_authorized':False}
        self.con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',('source',json.dumps(self.value),json.dumps(self.parent)))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('r1',json.dumps({'enabled':False})))
        self.bound=dict(issue_id='r1',author='author',enabled=False,minimum_calls=8,description='exact')
        self.fx=Mock();self.fx.plan.return_value=({'root_issue':'root'},{'plan':self.plan})
        self.fx.issue.side_effect=lambda key:dict(id='root',status='blocked') if key=='root' else dict(id=key,status='todo',assignee_id=None,description='exact')
        self.fx.remaining_calls.return_value=300;self.fx.available.return_value=True
        self.patch=patch.object(admission,'Effects',return_value=self.fx);self.patch.start();self.addCleanup(self.patch.stop)
        self.binding=patch.object(admission.dispatch,'binding',side_effect=lambda *args:self.bound);self.binding.start();self.addCleanup(self.binding.stop)
    def request(self):return admission.request(self.b,'source')
    def reconcile(self):return admission.reconcile(self.b,'source')
    def enabled(self,issue='r1'):return json.loads(self.con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])['enabled']
    def test_explicit_request_is_paused_and_under_budget_never_activates(self):
        self.assertEqual(self.request()['stage'],'awaiting_budget');self.assertFalse(self.enabled())
        self.fx.remaining_calls.return_value=206
        self.assertEqual(self.reconcile()['stage'],'awaiting_budget');self.assertFalse(self.enabled());self.fx.wake.assert_not_called()
    def test_budget_and_capacity_then_exactly_once_activation_without_wakeup(self):
        self.request();self.fx.available.return_value=False
        self.assertEqual(self.reconcile()['stage'],'awaiting_capacity');self.assertFalse(self.enabled())
        self.fx.available.return_value=True
        result=self.reconcile();self.assertTrue(self.enabled());self.assertFalse(result['release_homologated'])
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps({'enabled':False}),))
        self.assertEqual(self.reconcile(),result);self.assertFalse(self.enabled());self.fx.wake.assert_not_called()
    def test_r2_waits_for_live_dependency_and_is_activated_without_reopening_r1(self):
        self.request();self.reconcile()
        self.parent['r1_gate']={'approved':'actual'}
        self.con.execute('UPDATE remediation_executions SET state=?',(json.dumps(self.parent),))
        self.bound=None;self.assertEqual(self.reconcile()['stage'],'awaiting_dependency')
        self.bound=dict(issue_id='r2',author='author',enabled=False,minimum_calls=8,description='exact')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('r2',json.dumps({'enabled':False})))
        self.fx.remaining_calls.return_value=20
        result=self.reconcile();self.assertEqual(set(result['steps']),{'R1','R2'});self.assertTrue(self.enabled('r2'))
        self.fx.wake.assert_not_called()
    def test_cancelled_root_native_drift_or_dependency_hold_cannot_activate(self):
        self.request();self.fx.issue.side_effect=lambda key:dict(id=key,status='cancelled')
        self.assertEqual(self.reconcile()['category'],'admission_root_not_active');self.assertFalse(self.enabled())
    def test_changed_contract_or_unrecorded_activation_is_rejected(self):
        self.request();self.value['original_depth']=1
        self.con.execute('UPDATE remediation_executions SET contract=?',(json.dumps(self.value),))
        with self.assertRaises(ValueError):self.reconcile()
        self.assertFalse(self.enabled())

    def test_tick_retains_precondition_failure_instead_of_repeating_it(self):
        self.request();self.fx.plan.side_effect=ValueError('approval changed')
        admission.tick(self.b)
        self.assertEqual(self.reconcile()['category'],'admission_precondition_failed');self.assertFalse(self.enabled())
        count=self.fx.plan.call_count;admission.tick(self.b);self.assertEqual(self.fx.plan.call_count,count)

    def test_no_registration_or_missing_r2_can_dispatch(self):
        self.assertIsNone(self.reconcile());self.fx.wake.assert_not_called()
        self.request();self.bound['enabled']=True
        self.assertEqual(self.reconcile()['category'],'unrecorded_phase_activation');self.fx.wake.assert_not_called()
