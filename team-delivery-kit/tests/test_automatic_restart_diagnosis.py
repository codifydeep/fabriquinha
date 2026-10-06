import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

import automatic_restart_diagnosis as recovery

ISSUE = '11111111-1111-4111-8111-111111111111'
SOURCE = '22222222-2222-4222-8222-222222222222'


class AutomaticRestartDiagnosisTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.private = Path(tmp.name); (self.private / 'host-service').mkdir()
        self.status = dict(label='HOST-1', issue_id=ISSUE, stage='escalation_required',
                           category=recovery.CATEGORY)
        self.managed = dict(route=dict(issue_id=ISSUE, enabled=True, test_first=True,
            author='author', cto='cto'), state=dict(stage='test_first_blocked', source_task=SOURCE,
            data=json.dumps(dict(phase='test_first', error='test_first_correction_failed_after_cto_diagnosis'))))
        self.receipt = dict(request=dict(issue_id=ISSUE, source_task=SOURCE),
            proof=dict(baseline_unchanged=True, red_verified=False, delivery_approval=False),
            author_retry_authorized=False, delivery_approval=False)
        self.operation = Mock(return_value=self.receipt)
        self.path = self.private / 'host-service' / 'HOST-1.restart-diagnosis.json'

    def run_reconcile(self):
        return recovery.reconcile(self.private, 'delivery-kit-port2', self.status,
                                  self.managed, self.operation)

    def test_qualified_registration_once_never_retries_author(self):
        self.assertTrue(self.run_reconcile()); self.assertTrue(self.run_reconcile())
        self.operation.assert_called_once()
        self.assertEqual(self.operation.call_args.args[1], recovery.REGISTER)
        self.assertFalse(json.loads(self.path.read_text())['receipt']['author_retry_authorized'])

    def test_uncertain_transport_only_reads_durable_result_after_restart(self):
        self.operation.side_effect = subprocess.TimeoutExpired('fixed-command', 60)
        self.assertFalse(self.run_reconcile())
        self.operation.side_effect = None
        self.assertTrue(self.run_reconcile())
        self.assertEqual(self.operation.call_args.args[1], recovery.LOOKUP)

    def test_absent_result_blocks_without_duplicate_registration(self):
        self.operation.side_effect = [ValueError('rejected'), None]
        self.assertFalse(self.run_reconcile()); self.assertFalse(self.run_reconcile())
        self.assertFalse(self.run_reconcile()); self.assertEqual(self.operation.call_count, 2)
        self.assertEqual(json.loads(self.path.read_text())['stage'], 'diagnosis_blocked')

    def test_wrong_scope_completed_and_ordinary_errors_never_register(self):
        for changed in (dict(stage='deployed_qa_passed'), dict(category='ordinary_failure'),
                        dict(issue_id='other')):
            with self.subTest(changed=changed):
                original = self.status.copy(); self.status.update(changed)
                self.assertFalse(self.run_reconcile()); self.status = original
        self.operation.assert_not_called(); self.assertFalse(self.path.exists())

    def test_new_source_cannot_reuse_previous_registration(self):
        self.assertTrue(self.run_reconcile())
        self.managed['state']['source_task'] = '33333333-3333-4333-8333-333333333333'
        self.assertFalse(self.run_reconcile()); self.operation.assert_called_once()

    def test_diagnostic_cannot_claim_red_or_delivery_approval(self):
        for field in ('red_verified', 'delivery_approval'):
            with self.subTest(field=field):
                self.receipt['proof'][field] = True
                self.assertFalse(recovery.valid(self.receipt, ISSUE, SOURCE))
                self.receipt['proof'][field] = False

    def test_symlink_receipt_cannot_redirect_runtime_write(self):
        target = self.private / 'outside'; target.write_text('unchanged')
        self.path.symlink_to(target)
        with self.assertRaises(ValueError): self.run_reconcile()
        self.operation.assert_not_called(); self.assertEqual(target.read_text(), 'unchanged')

    def test_modified_registered_receipt_is_not_a_resume_authorization(self):
        self.assertTrue(self.run_reconcile())
        prior = json.loads(self.path.read_text())
        prior['receipt']['proof']['delivery_approval'] = True
        self.path.write_text(json.dumps(prior))
        self.assertFalse(self.run_reconcile()); self.operation.assert_called_once()
