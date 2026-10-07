import copy,hashlib,unittest
from broker import calibration_rework as lane
from broker.calibration_preflight_recovery import check_policy,qualify


class PreflightRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.execution='11111111-1111-4111-8111-111111111111'
        self.config=dict(issue_id='issue',cto='cto',format_revision=1,source_task='source',
            diagnostic={'phase':'positive_reference'},criteria={'A01':'unchanged'},paths=['/evidence/candidate/tests/test_new.py'])
        self.state=dict(stage='blocked',category='calibration_rework_rejected',cto_wakeup='wake')
        self.task=dict(status='failed',agent_id='cto',issue_id='issue',wakeup_id='wake',
            handoff_note='CALIBRATION GATE REWORK\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\nDELIVERY_TYPED_DECISION_V1')
        self.reads={self.config['paths'][0]:dict(lines=10,total_lines=10)}
        self.receipt=dict(operation='local_request_rejection_v1',execution_id=self.execution,request_sha256='a'*64,
            stage='contract',origin={'module':'typed_decision_contract','line':378},exception_type='ValueError',
            error_sha256=hashlib.sha256(b'observed non-approving test diagnosis contract required').hexdigest(),
            retry_authorized=False,delivery_approval=False)

    def test_current_policy_passes_schema_and_adapter_without_fabricating_read_evidence(self):
        self.assertEqual(len(check_policy(lane,self.config,self.state)),64)
        self.assertEqual(self.reads[self.config['paths'][0]]['lines'],10)

    def test_only_exact_closed_planner_preflight_with_complete_reads_qualifies(self):
        qualify(self.config,self.state,self.task,self.reads,self.receipt,self.execution)
        for change in [dict(stage='upstream'),dict(execution_id='22222222-2222-4222-8222-222222222222'),
                       dict(error_sha256='b'*64),dict(origin={'module':'decision_schema','line':378}),dict(delivery_approval=True)]:
            with self.assertRaises(ValueError):qualify(self.config,self.state,self.task,self.reads,{**self.receipt,**change},self.execution)
        with self.assertRaises(ValueError):qualify(self.config,self.state,self.task,{},self.receipt,self.execution)
        with self.assertRaises(ValueError):qualify(self.config,self.state,{**self.task,'status':'completed'},self.reads,self.receipt,self.execution)
        with self.assertRaises(ValueError):qualify(self.config,{**self.state,'author_wakeup':'wake'},self.task,self.reads,self.receipt,self.execution)
