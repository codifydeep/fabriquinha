import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import test_remediation_parent_delivery as fixtures
from portable_remediation_intake import prepare
from remediation_publication_schedule import reconcile


class RemediationPublicationScheduleTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.RemediationParentDeliveryTests();f.setUp();self.f=f
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup);self.root=Path(self.directory.name)
        self.stage={**f.stage,'contract_path':self.root/'contract.json'}
        self.stage['contract_path'].write_text(json.dumps(self.stage['contract']))
        self.project=self.root/'project.json';self.project.write_text('{}')
        self.parent=f.bundle['context']['remediation_parent']
        self.fx=Mock();self.fx.candidate.return_value='r2';self.fx.approved.return_value=f.receipt['delivery']
        self.fx.input.return_value=f.bundle;self.fx.parent.return_value={'id':'root','status':'todo'}
        self.fx.processes.return_value=[];self.fx.launch.return_value=123
        self.fx.status.return_value=None;self.fx.receipt.return_value=None;self.fx.now.return_value=100
        self.fx.publish.return_value={'stage':'parent_projected'}

    def invoke(self):
        with patch('remediation_publication_schedule.bundle',return_value=self.f.bundle):
            return reconcile(self.root,self.stage,self.parent,self.project,effects=self.fx)

    def test_no_candidate_or_cancelled_root_never_prepares_or_launches(self):
        self.fx.candidate.return_value=None
        self.assertIsNone(self.invoke());self.fx.launch.assert_not_called()
        self.fx.candidate.return_value='r2';self.fx.parent.return_value={'id':'root','status':'cancelled'}
        with self.assertRaises(ValueError):self.invoke()
        self.fx.launch.assert_not_called()

    def test_intent_precedes_unique_launch_and_live_handle_is_observed(self):
        def launch(paths,*args):
            intent=paths['intent'].with_name(self.f.bundle['context']['label']+'.controller.json')
            self.assertTrue(json.loads(intent.read_text())['launch_attempted'])
            return 123
        self.fx.launch.side_effect=launch
        self.assertEqual(self.invoke()['stage'],'running')
        self.fx.processes.return_value=[123]
        self.assertEqual(self.invoke()['stage'],'running');self.fx.launch.assert_called_once()

    def test_uncertain_launch_is_lookup_only_never_repeated(self):
        self.fx.launch.side_effect=TimeoutError('uncertain')
        self.assertEqual(self.invoke()['stage'],'launch_observation_pending')
        self.fx.processes.return_value=[123]
        self.assertEqual(self.invoke()['stage'],'running');self.fx.launch.assert_called_once()

    def test_missing_handle_blocks_without_relaunch(self):
        self.invoke();self.fx.processes.return_value=[]
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['owner'],'techlead');self.fx.launch.assert_called_once()
        self.assertEqual(self.invoke(),result);self.fx.launch.assert_called_once()

    def test_exact_original_handle_can_resolve_false_missing_observation_without_relaunch(self):
        self.invoke();self.invoke()
        self.fx.processes.return_value=[999]
        self.assertEqual(self.invoke()['stage'],'blocked')
        self.fx.processes.return_value=[123]
        result=self.invoke()
        self.assertEqual(result['stage'],'running')
        self.assertFalse(result['handle_recovery']['process_relaunched'])
        self.assertEqual(result['handle_recovery']['previous_state']['category'],'r3_controller_handle_missing')
        self.fx.launch.assert_called_once()

    def test_real_delivery_projects_parent_without_new_launch(self):
        self.fx.receipt.return_value=self.f.receipt
        self.assertEqual(self.invoke()['stage'],'parent_projected')
        self.fx.launch.assert_not_called();self.fx.publish.assert_called_once()

    def test_live_controller_without_progress_is_bounded_and_never_called_delivered(self):
        self.invoke();self.fx.processes.return_value=[123];self.fx.now.return_value=1901
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['category'],'r3_progress_deadline');self.fx.publish.assert_not_called()
        self.fx.launch.assert_called_once()
        self.fx.receipt.return_value=self.f.receipt
        self.assertEqual(self.invoke()['stage'],'parent_projected')

    def test_disappeared_dependency_remains_visible_without_another_launch(self):
        self.invoke();self.fx.candidate.return_value=None
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['category'],'r3_dependency_not_qualified')
        self.fx.launch.assert_called_once()

    def test_changed_expected_revision_does_not_adopt_old_controller(self):
        self.invoke();other={**self.f.bundle,'original_depth':1}
        with patch('remediation_publication_schedule.bundle',return_value=other):
            with self.assertRaises(ValueError):reconcile(self.root,self.stage,self.parent,self.project,effects=self.fx)
        self.fx.launch.assert_called_once()

    def test_sequence_hook_calls_scheduler_and_publishes_only_safe_stage(self):
        from dependent_sequence import supervise_recovery_publication
        label=self.parent['label']
        (self.root/('portable-context-'+label+'.json')).write_text(json.dumps(self.parent))
        plan={'sha256':'a'*64,'project_config':self.project,'stages':[{'spec':{'label':'FIRST-1'}},self.stage]}
        ledger={'stage':'blocked','plan_sha256':'a'*64,'active':label,'completed':['FIRST-1'],'issues':{label:'root'}}
        cli=Mock(return_value={})
        with patch('remediation_publication_schedule.reconcile',return_value={'stage':'running','pid':123,'identity':'private'}) as schedule:
            result=supervise_recovery_publication(ledger,plan,self.root,cli,'delivery-kit-port2')
        self.assertEqual(result['stage'],'running');schedule.assert_called_once()
        value=cli.call_args.args[6];self.assertEqual(json.loads(value),{'stage':'running'})
        with patch('remediation_publication_schedule.reconcile') as schedule:
            self.assertIsNone(supervise_recovery_publication({**ledger,'plan_sha256':'0'*64},plan,self.root,cli,'delivery-kit-port2'))
        schedule.assert_not_called()

    def test_publication_only_missing_approval_never_recovers_author(self):
        import portable_delivery as driver
        context=self.f.bundle['context']
        with patch.object(driver,'configure_run'),patch.object(driver,'read_context',return_value=context),\
             patch.object(driver,'reconcile',side_effect=driver.WaitingApproval()),\
             patch.object(driver,'recover_implementation_worker') as recover,patch.object(driver,'status') as status:
            driver.run_controller({'schema_version':1})
        recover.assert_not_called();self.assertEqual(status.call_args.kwargs['category'],'approved_recovery_delivery_unavailable')

    def test_publication_only_rejects_recursive_test_revision(self):
        import portable_delivery as driver
        with patch.object(driver,'configure_run'),patch.object(driver,'read_context',return_value=self.f.bundle['context']),\
             patch.object(driver,'RUN_SPEC',{'label':'R3'}),\
             patch.object(driver,'reconcile',side_effect=driver.RecoveryEscalation('test_revision_required:missing')),\
             patch('portable_test_revision_recovery.schedule') as recursive,patch.object(driver,'status'):
            driver.run_controller({'schema_version':1})
        recursive.assert_not_called()
