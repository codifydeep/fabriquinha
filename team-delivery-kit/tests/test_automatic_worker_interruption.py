import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
import automatic_worker_interruption as recovery

ISSUE='11111111-1111-4111-8111-111111111111'
SOURCE='22222222-2222-4222-8222-222222222222'
CTO='33333333-3333-4333-8333-333333333333'


class AutomaticWorkerInterruptionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.private=Path(tmp.name);(self.private/'host-service').mkdir()
        self.status=dict(label='AUTOLOSS-1',issue_id=ISSUE,stage='escalation_required',category=recovery.CATEGORY)
        self.managed=dict(route=dict(issue_id=ISSUE,enabled=True,author='author',cto='cto'),
            state=dict(source_task=SOURCE,stage='technical_decision_required',owner='cto',data=json.dumps(dict(
                source_status='failed',source_failure_reason='agent_error.process_failure',error='author_execution_failed',
                target='cto',recipient_task=CTO,decision=dict(action='escalate_cto',optional_files=[]),
                phase_evidence=dict(phase='implementation',red_exit_code=1,independent_test_review='approved',
                                    frozen_test_hashes={'tests/test_new.py':'a'*64})))))
        self.receipt=dict(request=dict(issue_id=ISSUE,source_task=SOURCE,decision_task=CTO),
            stage='qualified_cto_decision',operation='pre_tool_worker_interruption_recovery_v1',probe_status='passed',
            proof=dict(baseline_unchanged=True,frozen_tests_unchanged=True,red_verified=False,
                       diagnostic_only=True,delivery_approval=False),author_retry_authorized=False,delivery_approval=False)
        self.path=self.private/'host-service'/'AUTOLOSS-1.worker-interruption.json'

    def run_reconcile(self,operation):
        return recovery.reconcile(self.private,'delivery-kit-port2',self.status,self.managed,operation)

    def test_once_registers_after_readonly_fault_check(self):
        operation=Mock(side_effect=[True,self.receipt])
        self.assertTrue(self.run_reconcile(operation));self.assertTrue(self.run_reconcile(operation))
        self.assertEqual(operation.call_count,2)
        self.assertEqual(operation.call_args_list[0].args[1],recovery.PRECHECK)
        self.assertEqual(operation.call_args_list[1].args[1],recovery.REGISTER)

    def test_no_fault_or_wrong_scope_does_not_create_intent(self):
        operation=Mock(return_value=False)
        self.assertFalse(self.run_reconcile(operation));self.assertFalse(self.path.exists())
        self.status['category']='ordinary_failure'
        self.assertFalse(self.run_reconcile(operation));operation.assert_called_once()

    def test_uncertain_registration_only_looks_up_existing_receipt(self):
        operation=Mock(side_effect=[True,subprocess.TimeoutExpired('fixed',60),self.receipt])
        self.assertFalse(self.run_reconcile(operation));self.assertTrue(self.run_reconcile(operation))
        self.assertEqual(operation.call_args.args[1],recovery.LOOKUP)

    def test_missing_uncertain_result_blocks_without_registering_again(self):
        operation=Mock(side_effect=[True,ValueError('unknown'),None])
        self.assertFalse(self.run_reconcile(operation));self.assertFalse(self.run_reconcile(operation))
        self.assertFalse(self.run_reconcile(operation));self.assertEqual(operation.call_count,3)

    def test_pending_probe_advances_same_durable_request(self):
        pending=dict(self.receipt,stage='probe_pending')
        operation=Mock(side_effect=[True,pending,self.receipt])
        self.assertFalse(self.run_reconcile(operation));self.assertTrue(self.run_reconcile(operation))
        self.assertEqual(operation.call_args.args[1],recovery.ADVANCE)

    def test_repeated_pending_probe_is_bounded(self):
        pending=dict(self.receipt,stage='probe_pending')
        operation=Mock(side_effect=[True,pending,pending,pending])
        for _ in range(6):self.assertFalse(self.run_reconcile(operation))
        self.assertEqual(operation.call_count,4)
        self.assertEqual(json.loads(self.path.read_text())['stage'],'diagnosis_blocked')

    def test_fake_approval_and_new_source_are_not_refresh_authority(self):
        operation=Mock(side_effect=[True,self.receipt]);self.assertTrue(self.run_reconcile(operation))
        prior=json.loads(self.path.read_text());prior['receipt']['author_retry_authorized']=True
        self.path.write_text(json.dumps(prior))
        self.assertFalse(self.run_reconcile(operation))
        self.managed['state']['source_task']=CTO;self.assertFalse(self.run_reconcile(operation))
        self.assertEqual(operation.call_count,2)

    def test_transport_observation_failure_is_bounded_and_bad_receipt_denied(self):
        operation=Mock(side_effect=[True,ValueError('unknown'),ValueError('unknown')])
        for _ in range(5):self.assertFalse(self.run_reconcile(operation))
        self.assertEqual(operation.call_count,3)
        self.assertEqual(json.loads(self.path.read_text())['stage'],'diagnosis_blocked')
        self.assertFalse(recovery.valid('text',{}));self.assertFalse(recovery.valid(dict(proof='text'),{}))
