import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import browser_qa_composition as composition
import portable_browser_qa as qa


class ComposedQaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = {'scenario': 'feedback-board-filter-v1', 'browser_image': 'sha256:'+'b'*64}
        self.baseline_config = {**self.config, 'scenario': 'feedback-board-demo-mode-ui-v1'}
        self.identity = {'source_sha':'a'*40, 'deployed_container_id':'d'*64,
                         'application_image':'sha256:'+'c'*64, 'runtime_env':{'FEEDBACK_DB_PATH':'/tmp/feedback.db'},
                         'config':self.config, 'scenario_sha256':hashlib.sha256(qa.SCRIPT.read_bytes()).hexdigest()}
        self.baseline = {'identity':{**self.identity,'config':self.baseline_config},
                         'status':'passed','cleanup':'passed','automated':True,
                         'result':{'status':'passed','source_sha':'a'*40},
                         'screenshot_sha256':hashlib.sha256(b'png').hexdigest()}
        self.path=self.folder/(composition.receipt_key(self.baseline['identity'])+'.json')
        self.path.write_text(json.dumps(self.baseline))
        self.path.with_suffix('.png').write_bytes(b'png')
        self.proof=composition.reference(self.folder,self.baseline)

    def verify(self,proof=None,identity=None):
        return composition.verify(self.folder,proof or self.proof,identity or self.identity,
                                  self.baseline_config,self.identity['scenario_sha256'])

    def test_exact_durable_baseline_is_bound_to_same_deployment(self):
        self.assertEqual(self.verify(),self.baseline)
        for field,value in (('source_sha','f'*40),('application_image','sha256:'+'f'*64),
                            ('deployed_container_id','f'*64),('runtime_env',{})):
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.verify(identity={**self.identity,field:value})

    def test_metadata_changed_receipt_screenshot_and_recipe_cannot_bypass_gate(self):
        self.path.write_text(json.dumps({**self.baseline,'status':'failed'}))
        with self.assertRaisesRegex(ValueError,'drift'):self.verify()
        forged=composition.reference(self.folder,{**self.baseline,'status':'failed'})
        with self.assertRaisesRegex(ValueError,'passed'):self.verify(proof=forged)
        self.path.write_text(json.dumps(self.baseline))
        self.path.with_suffix('.png').write_bytes(b'tampered')
        with self.assertRaises(ValueError):self.verify()
        self.path.with_suffix('.png').write_bytes(b'png')
        with self.assertRaises(ValueError):
            composition.verify(self.folder,self.proof,self.identity,self.baseline_config,'f'*64)
        with self.assertRaises(ValueError):self.verify(proof={**self.proof,'receipt_key':'../other'})

    def test_missing_or_failed_cleanup_is_not_baseline_acceptance(self):
        for change in ({'cleanup':'failed'},{'automated':False},{'result':{'status':'passed','source_sha':'f'*40}}):
            modified={**self.baseline,**change}
            self.path.write_text(json.dumps(modified))
            proof=composition.reference(self.folder,modified)
            with self.assertRaises(ValueError):self.verify(proof=proof)

    def test_baseline_failure_prevents_feature_execution(self):
        with patch.object(qa,'baseline_for',side_effect=lambda name: self.baseline_config['scenario'] if name==self.config['scenario'] else None), \
             patch.object(qa,'_qualify_one',side_effect=ValueError('baseline failed')) as runner:
            with self.assertRaisesRegex(ValueError,'baseline failed'):
                qa.qualify(config=self.config,deployed_container='app',source_sha='a'*40,
                           evidence_dir=self.folder,runtime_env=self.identity['runtime_env'])
            self.assertEqual(runner.call_count,1)

    def test_wrapper_runs_baseline_first_and_passes_durable_binding(self):
        with patch.object(qa,'baseline_for',side_effect=lambda name: self.baseline_config['scenario'] if name==self.config['scenario'] else None), \
             patch.object(qa,'_qualify_one',side_effect=[self.baseline,{'status':'passed'}]) as runner:
            qa.qualify(config=self.config,deployed_container='app',source_sha='a'*40,
                       evidence_dir=self.folder,runtime_env=self.identity['runtime_env'])
            self.assertEqual(runner.call_args_list[0].kwargs['config'],self.baseline_config)
            self.assertEqual(runner.call_args_list[1].kwargs['baseline_proof'],self.proof)

    def test_cached_feature_pass_without_frozen_baseline_reference_is_rejected(self):
        candidate={**self.baseline,'identity':copy.deepcopy(self.identity)}
        path=self.folder/(composition.receipt_key(self.identity)+'.json')
        path.write_text(json.dumps(candidate));path.with_suffix('.png').write_bytes(b'png')
        deployed={'Image':self.identity['application_image'],'Id':self.identity['deployed_container_id'],
                  'State':{'Running':True}}
        metadata={'Config':{'Labels':{'delivery-kit.source-sha':'a'*40}}}
        with patch.object(qa,'inspect',side_effect=[deployed,metadata]),patch.object(qa,'docker') as docker:
            with self.assertRaisesRegex(ValueError,'binding drift'):
                qa._qualify_one(config=self.config,deployed_container='app',source_sha='a'*40,
                    evidence_dir=self.folder,runtime_env=self.identity['runtime_env'],
                    baseline_proof=self.proof,baseline_config=self.baseline_config)
            docker.assert_not_called()

    def test_nested_baselines_are_revalidated_in_order_on_same_deployment(self):
        config={**self.config,'scenario':'feedback-board-count-ui-v1'}
        detail={**config,'scenario':'feedback-board-detail-ui-v1'}
        legacy={**config,'scenario':'feedback-board-demo-mode-ui-v1'}
        with patch.object(qa,'_qualify_one',side_effect=[self.baseline,{'status':'passed'},{'status':'passed'}]) as runner, \
             patch.object(composition,'reference',side_effect=[{'legacy':'proof'},{'detail':'proof'}]):
            qa.qualify(config=config,deployed_container='app',source_sha='a'*40,
                       evidence_dir=self.folder,runtime_env=self.identity['runtime_env'])
            self.assertEqual([call.kwargs['config'] for call in runner.call_args_list],[legacy,detail,config])
            self.assertEqual(runner.call_args_list[1].kwargs['baseline_config'],legacy)
            self.assertEqual(runner.call_args_list[2].kwargs['baseline_config'],detail)
            self.assertEqual(runner.call_args_list[2].kwargs['baseline_proof'],{'detail':'proof'})

    def test_fixed_dependency_cycle_fails_before_docker_execution(self):
        with patch.object(qa,'baseline_for',return_value=self.config['scenario']), \
             patch.object(qa,'_qualify_one') as runner:
            with self.assertRaisesRegex(ValueError,'cyclic'):
                qa.qualify(config=self.config,deployed_container='app',source_sha='a'*40,
                           evidence_dir=self.folder,runtime_env=self.identity['runtime_env'])
            runner.assert_not_called()
