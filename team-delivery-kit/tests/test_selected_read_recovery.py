import json
import unittest
from unittest.mock import patch
from broker import handoffs,selected_read_recovery as recovery,test_first_handoffs
import test_pre_red_infra_replan as infrastructure_tests
from test_test_first_handoffs import Effects


class SelectedReadRecoveryTests(unittest.TestCase):
    def setUp(self):
        infrastructure_tests.InfrastructureReplanTests.setUp(self)
        self.b.PREFIX='delivery-kit-port2'
        self.b.test_artifact_phase_context=lambda *args:'\nDELIVERY_DETERMINISTIC_READ_V1\n'
        self.decision=dict(action='request_correction',reason='Resume tests only.',optional_files=[])
        self.runs[0]['wakeup_id']='correction-wake'
        self.runs[1]['wakeup_id']='cto-wake'
        with self.b.db() as c:
            c.execute("UPDATE leases SET status='closed'")
            handoffs.save(c,self.source,self.issue,'test_first_blocked','cto',
                {'phase':'test_first','error':'test_first_correction_failed_after_cto_diagnosis'},2)
            handoffs.save(c,'prior-source',self.issue,'test_first_cto_correction_wait','author',
                dict(cto_task=self.cto,decision=self.decision,test_first_cto_wakeup='cto-wake',
                     test_first_correction_wakeup='correction-wake'),1)
        self.event=dict(execution_id='execution',call_number=42,category='invalid_forced_argument')

    def register(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs),patch(
                'broker.handoff_runtime.Effects.decision',return_value=self.decision),patch(
                'broker.artifact_transport_recovery.verify_preserved_failure',return_value=self.proof),patch(
                'broker.selected_read_recovery.rejected_read',return_value=self.event):
            return recovery.register(self.b,self.payload)

    def test_once_bound_recovery_preserves_sponsor_and_blocker(self):
        r=self.register();self.assertEqual(self.register(),r)
        self.assertEqual(r['decision'],self.decision)
        self.assertFalse(r['delivery_approval'])
        with self.b.db() as c:
            row=handoffs.load(c,self.source)
            self.assertEqual(row['stage'],'test_first_selected_read_recovery_pending')
            self.assertIsNone(c.execute('SELECT 1 FROM test_first_red').fetchone())
        effects=Effects(self.b)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],row,effects)
        self.assertEqual(effects.wakeups[0][0][1],'author')
        with self.b.db() as c:row=handoffs.load(c,self.source)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],row,effects)
        self.assertEqual(len(effects.wakeups),1)

    def test_missing_changed_contract_rejects_recovery(self):
        self.b.test_artifact_phase_context=lambda *args:''
        with self.assertRaises(ValueError):self.register()

    def test_wrong_correction_wakeup_or_cto_action_rejects(self):
        self.runs[0]['wakeup_id']='unrelated'
        with self.assertRaises(ValueError):self.register()
        self.runs[0]['wakeup_id']='correction-wake';self.decision['action']='escalate_cto'
        with self.assertRaises(ValueError):self.register()

    def test_existing_tools_or_red_cannot_be_hidden(self):
        with self.b.db() as c:c.execute('INSERT INTO tool_events VALUES (?,?)',('execution',1))
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as c:
            c.execute('DELETE FROM tool_events');c.execute('INSERT INTO test_first_red VALUES (?)',(self.issue,))
        with self.assertRaises(ValueError):self.register()

    def test_changed_baseline_or_later_author_rejects(self):
        self.proof['baseline_unchanged']=False
        with self.assertRaises(ValueError):self.register()
        self.proof['baseline_unchanged']=True
        self.runs.append(dict(id='later',agent_id='author',status='failed',created_at='03'))
        with self.assertRaises(ValueError):self.register()

    def test_unrelated_proxy_log_is_not_failure_evidence(self):
        self.b.docker=lambda *args:dict(State=dict(Running=True),Config=dict(Labels={'com.docker.compose.project':self.b.PREFIX}))
        self.b.docker_stdout=lambda *args,**kw:json.dumps(dict(event='model_proxy_request',execution_id='other',
            status=502,artifact_selected_tool='read_file',artifact_rejection_category='invalid_forced_argument',call_number=42))
        with self.assertRaises(ValueError):recovery.rejected_read(self.b,'execution')


if __name__=='__main__':unittest.main()
