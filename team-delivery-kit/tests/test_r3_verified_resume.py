import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import test_remediation_parent_delivery as fixtures
from portable_remediation_intake import prepare,digest
from release_eval import save_receipt
from r3_verified_resume import resume,Effects,verify_lineage


class R3VerifiedResumeTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.RemediationParentDeliveryTests();fixture.setUp();self.bundle=fixture.bundle
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.paths=prepare(self.root,self.bundle)
        self.controller=self.paths['intent'].with_name(self.bundle['context']['label']+'.controller.json')
        self.blocked=dict(identity='a'*64,stage='blocked',category='r3_controller_handle_missing',pid=123,release_homologated=False)
        save_receipt(self.controller,self.blocked)
        context=self.bundle['context'];proof=context['remediation_expected']
        self.evidence=dict(operation='r3_incident_evidence_v1',root_issue=context['remediation_parent']['issue_id'],
            source_task=proof['source_task'],controller_identity='a'*64,controller_episode_sha256=digest(self.blocked),
            bundle_sha256=digest(self.bundle),r2_proof_sha256=digest(proof),category='r3_controller_handle_missing',
            facts={'F01':'controller_handle_missing'},execution_authorized=False,release_homologated=False,
            previous_incident_sha256='d'*64,experiment_receipt_sha256='e'*64,experiment_result_sha256='f'*64,
            experiment_history=['observe_existing_controller'])
        self.incident=digest(self.evidence)
        self.state=dict(stage='resume_verification_pending',incident_sha256=self.incident,post_experiment=True,escalated=True,
            proposal=dict(action='propose_resume',experiment='none'),review={'decision':'approve_resume'},
            execution_authorized=False,release_homologated=False)
        save_receipt(self.root/'r3-incidents'/(self.incident+'.json'),dict(config={'evidence':self.evidence},state=self.state))
        self.fx=Mock();self.fx.now.return_value=100;self.fx.processes.return_value=[]
        self.fx.verify.return_value={'operation':'verified_r3_resume_inputs_v1','bundle_sha256':digest(self.bundle),
            'physical_manifest_sha256':self.bundle['context']['remediation_expected']['delivery']['manifest_sha256'],
            'active_leases':0,'controller_count':0,'original_depth':2,'release_homologated':False}
        self.fx.launch.return_value=456
        self.stage=fixture.stage;self.project=self.root/'project.json'

    def invoke(self):return resume(self.root,self.state,self.bundle,self.stage,self.project,effects=self.fx)

    def test_current_proof_and_intent_precede_only_one_controller_launch(self):
        def launch(*args):
            saved=json.loads(self.controller.read_text())
            self.assertEqual(saved['stage'],'resume_launch_intent')
            self.assertEqual(saved['previous_hold'],self.blocked)
            self.assertFalse(saved['release_homologated'])
            self.assertTrue(saved['controller_resume_authorized'])
            return 456
        self.fx.launch.side_effect=launch
        result=self.invoke();self.assertEqual(result['stage'],'running');self.assertEqual(result['pid'],456)
        self.fx.processes.return_value=[456]
        self.assertEqual(self.invoke()['stage'],'running');self.fx.launch.assert_called_once()

    def test_approval_cannot_resume_changed_hold_or_bundle(self):
        save_receipt(self.controller,{**self.blocked,'pid':789})
        with self.assertRaises(ValueError):self.invoke()
        self.fx.launch.assert_not_called()

    def test_native_or_frozen_verification_failure_is_visible_without_launch(self):
        self.fx.verify.side_effect=ValueError('native approval moved')
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['owner'],'cto');self.fx.launch.assert_not_called()

    def test_active_process_worker_or_wrong_manifest_never_launches(self):
        for change in (dict(active_leases=1),dict(controller_count=1),dict(physical_manifest_sha256='c'*64)):
            with tempfile.TemporaryDirectory() as directory:
                other=Path(directory);paths=prepare(other,self.bundle)
                save_receipt(paths['intent'].with_name(self.bundle['context']['label']+'.controller.json'),self.blocked)
                save_receipt(other/'r3-incidents'/(self.incident+'.json'),dict(config={'evidence':self.evidence},state=self.state))
                self.fx.verify.return_value={**self.fx.verify.return_value,**change}
                result=resume(other,self.state,self.bundle,self.stage,self.project,effects=self.fx)
                self.assertEqual(result['stage'],'blocked')
        self.fx.launch.assert_not_called()

    def test_uncertain_launch_is_observed_not_repeated(self):
        self.fx.launch.side_effect=TimeoutError('ack lost')
        self.assertEqual(self.invoke()['stage'],'resume_observation_pending')
        self.fx.processes.return_value=[456]
        self.assertEqual(self.invoke()['stage'],'running');self.fx.launch.assert_called_once()

    def test_missing_handle_after_authorized_attempt_does_not_launch_again(self):
        self.invoke();self.fx.processes.return_value=[]
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['category'],'authorized_resume_handle_missing')
        self.invoke();self.fx.launch.assert_called_once()

    def test_text_only_or_non_post_experiment_resume_has_no_authority(self):
        for change in (dict(stage='retained_hold'),dict(post_experiment=False),dict(execution_authorized=True)):
            with self.assertRaises(ValueError):resume(self.root,{**self.state,**change},self.bundle,self.stage,self.project,effects=self.fx)
        self.fx.launch.assert_not_called()

    def test_crash_during_verification_does_not_repeat_probe_or_launch(self):
        value={**self.blocked,'stage':'resume_verification_intent','resume_incident_sha256':self.incident,
               'previous_hold':self.blocked,'controller_resume_authorized':False}
        save_receipt(self.controller,value)
        result=self.invoke();self.assertEqual(result['category'],'authorized_resume_verification_unobservable')
        self.fx.verify.assert_not_called();self.fx.launch.assert_not_called()

    def test_ambiguous_or_changed_pid_is_not_adopted(self):
        self.invoke();self.fx.processes.return_value=[456,789]
        self.assertEqual(self.invoke()['category'],'authorized_resume_handle_ambiguous')
        self.fx.launch.assert_called_once()

    def test_private_decision_drift_and_unbound_bundle_cannot_launch(self):
        for change in (dict(review={'decision':'retain_hold'}),dict(incident_sha256='a'*64)):
            with self.assertRaises((ValueError,FileNotFoundError)):
                resume(self.root,{**self.state,**change},self.bundle,self.stage,self.project,effects=self.fx)
        with self.assertRaises(ValueError):
            resume(self.root,self.state,{**self.bundle,'original_depth':1},self.stage,self.project,effects=self.fx)
        self.fx.launch.assert_not_called()

    def test_recorded_attempt_cannot_adopt_another_controller_identity(self):
        self.invoke();value=json.loads(self.controller.read_text())
        save_receipt(self.controller,{**value,'identity':'f'*64})
        self.fx.processes.return_value=[456]
        with self.assertRaises(ValueError):self.invoke()
        self.fx.launch.assert_called_once()

    def test_exact_real_effect_path_rechecks_native_and_hashes_before_launch(self):
        stage={**self.stage,'contract_path':self.root/'contract.json'}
        episode={**self.evidence,'controller_identity':digest(dict(bundle=self.bundle,
            project=str(self.project.resolve()),contract_path=str(stage['contract_path'].resolve()),instance='delivery-kit-port2'))}
        fx=Effects(self.root,'delivery-kit-port2');pub=Mock();fx.publication=pub
        pub.candidate.return_value=self.bundle['context']['issue_id']
        delivery=self.bundle['context']['remediation_expected']['delivery'];pub.approved.return_value=delivery
        pub.processes.return_value=[]
        with patch('r3_fixed_experiments.Effects') as fixed,\
             patch('r3_verified_resume.verify_lineage') as lineage,\
             patch('r3_verified_resume.make_bundle',return_value=self.bundle),\
             patch('r3_verified_resume.command',return_value='0') as query:
            fixed.return_value.snapshot.return_value=dict(status='passed',observation='snapshot_hashes_match',
                manifest_sha256=delivery['manifest_sha256'],file_count=62,total_bytes=1024)
            result=fx.verify(episode,self.state,self.bundle,stage,self.project,self.incident)
            self.assertEqual(result['active_leases'],0);self.assertEqual(result['physical_manifest_sha256'],delivery['manifest_sha256'])
            self.assertEqual(fixed.return_value.verify.call_count,2)
            lineage.assert_called_once();fixed.return_value.snapshot.assert_called_once()
            self.assertEqual(query.call_count,2);self.assertIn('WHERE status IN',query.call_args.args[-1])
            query.return_value='1'
            with self.assertRaises(ValueError):fx.verify(episode,self.state,self.bundle,stage,self.project,self.incident)
            fixed.return_value.snapshot.assert_called_once()

    def test_historical_experiment_receipt_cannot_be_forged_or_omitted(self):
        import test_r3_post_experiment as post
        from r3_post_experiment import next_evidence
        fixture=post.R3PostExperimentTests();fixture.setUp();self.addCleanup(fixture.tmp.cleanup)
        origin=fixture.evidence;state=fixture.state;journal=fixture.journal
        save_receipt(fixture.root/'r3-incidents'/(digest(origin)+'.json'),dict(config={'evidence':origin},state=state))
        current=next_evidence(origin,state,fixture.bundle,journal)
        verify_lineage(fixture.root,current,fixture.bundle)
        save_receipt(fixture.root/'r3-experiments'/(journal['identity']+'.json'),{**journal,'result_sha256':'c'*64})
        with self.assertRaises(ValueError):verify_lineage(fixture.root,current,fixture.bundle)
