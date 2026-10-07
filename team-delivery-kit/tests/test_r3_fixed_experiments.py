import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from portable_remediation_intake import digest
from r3_fixed_experiments import execute,Effects
from r3_snapshot_probe import probe


class R3FixedExperimentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bundle={'context':{'label':'REMEDIATION'+'A'*16+'-1','remediation_expected':{'delivery':{'manifest_sha256':'d'*64}}}}
        self.evidence={'bundle_sha256':digest(self.bundle),'controller_identity':'a'*64,'r2_proof_sha256':'b'*64}
        self.state=dict(stage='experiment_pending',incident_sha256=digest(self.evidence),review_task='review',
            proposal={'action':'request_experiment','experiment':'observe_existing_controller','execution_authorized':False},
            review={'decision':'approve_experiment'},execution_authorized=False,release_homologated=False)
        self.state['proposal_sha256']=digest(self.state['proposal'])
        self.fx=Mock();self.fx.verify.return_value=None;self.fx.now.return_value=100
        self.fx.run.return_value={'status':'passed','observation':'controller_absent','process_count':0}
        self.fx.observe.return_value=None

    def invoke(self):return execute(self.root,self.evidence,self.state,self.bundle,effects=self.fx)

    def test_immutable_intent_precedes_fixed_operation_and_result_is_durable(self):
        def run(experiment,bundle,journal):
            saved=json.loads(next((self.root/'r3-experiments').glob('*.json')).read_text())
            self.assertEqual(saved['stage'],'execution_intent')
            self.assertEqual(experiment,'observe_existing_controller')
            return self.fx.run.return_value
        self.fx.run.side_effect=run
        result=self.invoke();self.assertEqual(result['stage'],'experiment_recorded')
        self.assertFalse(result['execution_authorized']);self.assertFalse(result['release_homologated'])
        self.assertEqual(self.invoke(),result);self.fx.run.assert_called_once()

    def test_no_agent_shell_or_resume_or_unreviewed_plan_can_run(self):
        for change in (dict(proposal={**self.state['proposal'],'experiment':'shell'}),dict(stage='resume_verification_pending'),
                       dict(review={'decision':'retain_hold'}),dict(execution_authorized=True)):
            with self.assertRaises(ValueError):execute(self.root,self.evidence,{**self.state,**change},self.bundle,effects=self.fx)
        self.fx.run.assert_not_called()

    def test_obsolete_native_review_is_rechecked_before_operation(self):
        self.fx.verify.side_effect=ValueError('approval moved')
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['category'],'independent_review_not_current')
        self.fx.run.assert_not_called()
        self.assertEqual(self.invoke(),result)
        self.fx.verify.assert_called_once()

    def test_unknown_acknowledgment_observes_same_job_without_reexecution(self):
        self.fx.run.side_effect=TimeoutError('observation failed')
        self.assertEqual(self.invoke()['stage'],'observation_pending')
        self.fx.observe.return_value={'status':'passed','observation':'controller_absent','process_count':0}
        self.assertEqual(self.invoke()['stage'],'experiment_recorded')
        self.fx.run.assert_called_once();self.fx.observe.assert_called_once()

    def test_missing_result_or_functional_failure_never_becomes_success(self):
        self.fx.run.side_effect=TimeoutError()
        self.invoke();self.fx.now.return_value=1901
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['owner'],'cto');self.fx.run.assert_called_once()
        self.assertEqual(self.invoke(),result)

    def test_raw_output_paths_and_false_success_are_rejected(self):
        self.fx.run.return_value={'status':'passed','stdout':'secret','observation':'controller_absent'}
        result=self.invoke();self.assertEqual(result['stage'],'blocked')
        self.assertFalse(result['release_homologated'])

    def test_passed_status_cannot_substitute_other_experiment_or_missing_receipt(self):
        for value in ({'status':'passed','observation':'delivery_receipt_unavailable'},
                      {'status':'passed','observation':'controller_present','process_count':0},
                      {'status':'passed','observation':'github_ci_exact_sha','source_sha':'f'*40}):
            with tempfile.TemporaryDirectory() as directory:
                self.fx.run.return_value=value
                result=execute(Path(directory),self.evidence,self.state,self.bundle,effects=self.fx)
                self.assertEqual(result['stage'],'blocked')

    def test_snapshot_job_is_grouped_read_only_without_network_credentials_or_socket(self):
        delivery={'source_task':'source','volume':'delivery-kit-port2-snapshot-source','manifest_sha256':'a'*64}
        expected=dict(status='passed',observation='snapshot_hashes_match',manifest_sha256='a'*64,file_count=1,total_bytes=10)
        volume=[{'Labels':{'delivery-kit.owner':'delivery-kit-port2-broker-v1','delivery-kit.source-task':'source'}}]
        with patch('r3_fixed_experiments.command',side_effect=[json.dumps(volume),'sha256:'+'b'*64]),\
             patch('r3_fixed_experiments.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps(expected))) as run:
            self.assertEqual(Effects(self.root,'delivery-kit-port2').snapshot(delivery,{'identity':'c'*64}),expected)
        argv=run.call_args.args[0]
        self.assertIn('--rm',argv);self.assertIn('--read-only',argv)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',argv)
        self.assertEqual(argv[argv.index('--network')+1],'none')
        self.assertEqual(argv[argv.index('--user')+1],'10000:10000')
        self.assertNotIn('--env',argv);self.assertNotIn('--privileged',argv)
        self.assertFalse(any('docker.sock' in argument for argument in argv))

    def test_cross_instance_environment_cannot_query_native_approval(self):
        with patch('evalctl.PROJECT','delivery-kit-other'),patch('start_eval.cli') as native:
            with self.assertRaises(ValueError):Effects(self.root,'delivery-kit-port2').verify(self.evidence,self.state,self.bundle)
        native.assert_not_called()

    def test_supervisor_invokes_reviewed_experiment_and_projects_only_safe_fields(self):
        import test_remediation_parent_delivery as fixtures
        from portable_remediation_intake import prepare
        from r3_incident_runtime import supervise
        from release_eval import save_receipt
        fixture=fixtures.RemediationParentDeliveryTests();fixture.setUp()
        paths=prepare(self.root,fixture.bundle)
        parent=fixture.bundle['context']['remediation_parent']
        publication=dict(stage='blocked',identity='a'*64,category='r3_controller_handle_missing',release_homologated=False)
        save_receipt(paths['intent'].with_name(fixture.bundle['context']['label']+'.controller.json'),publication)
        with patch('r3_incident_runtime.reconcile',return_value=self.state),\
             patch('r3_fixed_experiments.execute',return_value={'stage':'experiment_recorded','result_sha256':'d'*64,'stdout':'not public'}) as execute:
            result=supervise(self.root,parent,publication,contract=fixture.stage['contract'])
        self.assertEqual(result['experiment'],{'stage':'experiment_recorded','result_sha256':'d'*64})
        self.assertEqual(execute.call_args.kwargs['contract'],fixture.stage['contract'])
        self.assertFalse(result['release_homologated'])


class SnapshotHashProbeTests(unittest.TestCase):
    def snapshot(self,root):
        (root/'test.py').write_text('assert True\n')
        data=(root/'test.py').read_bytes()
        manifest=json.dumps({'files':{'test.py':{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}}}).encode()
        (root/'manifest.json').write_bytes(manifest)
        return hashlib.sha256(manifest).hexdigest()

    def test_hash_probe_reads_artifact_without_running_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sha=self.snapshot(root)
            result=probe(root,sha)
            self.assertEqual(result['manifest_sha256'],sha);self.assertEqual(result['file_count'],1)
            self.assertEqual(result['observation'],'snapshot_hashes_match')

    def test_modified_file_extra_file_symlink_and_manifest_mismatch_fail(self):
        for mutation in ('change','extra','symlink','manifest'):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);sha=self.snapshot(root)
                if mutation=='change':(root/'test.py').write_text('assert False\n')
                if mutation=='extra':(root/'extra.py').write_text('pass')
                if mutation=='symlink':(root/'extra.py').symlink_to(root/'test.py')
                if mutation=='manifest':sha='a'*64
                with self.assertRaises(ValueError):probe(root,sha)
