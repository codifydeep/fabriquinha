import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import portable_browser_qa as qa
import portable_delivery
from portable_run_spec import validate
from test_portable_run_spec import spec
from test_portable_contract import contract


CONFIG = {'scenario': 'feedback-board-v1', 'browser_image': 'sha256:' + 'b' * 64}


class BrowserQaTests(unittest.TestCase):
    def test_fresh_receipt_is_json_stable_and_can_bind_baseline_without_retry(self):
        import subprocess
        import browser_qa_composition as composition
        deployed={'Image':'sha256:'+'a'*64,'Id':'id','State':{'Running':True}}
        metadata={'Config':{'Labels':{'delivery-kit.source-sha':'a'*40}}}
        output={'status':'passed','source_sha':'a'*40,'screenshot_base64':'cG5n'}
        def docker(*args,**kwargs):
            body=json.dumps(output) if args[0]=='run' and '/scenario.py' in args else ''
            return subprocess.CompletedProcess(args,0,body,'')
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(qa,'inspect',side_effect=lambda target,kind='container': deployed if kind=='container' else metadata), \
             patch.object(qa,'docker',side_effect=docker) as transport,patch.object(qa,'cleanup'):
            receipt=qa.qualify(config=CONFIG,deployed_container='app',source_sha='a'*40,
                    evidence_dir=directory,runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'})
            saved=json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(receipt,saved)
            proof=composition.reference(directory,receipt)
            self.assertEqual(proof['receipt_key'],composition.receipt_key(receipt['identity']))
            calls=transport.call_count
            cached=qa.qualify(config=CONFIG,deployed_container='app',source_sha='a'*40,
                    evidence_dir=directory,runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'})
            self.assertEqual(cached,receipt)
            self.assertEqual(transport.call_count,calls)

    def test_filter_scenarios_are_explicit_fixed_operations(self):
        for name in ('feedback-board-status-filter-api-v1', 'feedback-board-filter-v1',
                     'feedback-board-search-api-v1', 'feedback-board-search-v1'):
            config = {**CONFIG, 'scenario': name}
            self.assertEqual(qa.validate(config), config)
    def test_keyboard_scenario_is_an_explicit_fixed_operation(self):
        config = {**CONFIG, 'scenario': 'feedback-board-keyboard-dismiss-v1'}
        self.assertEqual(qa.validate(config), config)
    def test_accessibility_scenario_is_an_explicit_fixed_operation(self):
        config = {**CONFIG, 'scenario': 'feedback-board-pending-accessibility-v1'}
        self.assertEqual(qa.validate(config), config)

    def test_pending_submission_scenario_is_an_explicit_fixed_operation(self):
        config = {**CONFIG, 'scenario': 'feedback-board-pending-v1'}
        self.assertEqual(qa.validate(config), config)
    def test_config_requires_fixed_scenario_and_immutable_image(self):
        self.assertEqual(qa.validate(CONFIG), CONFIG)
        for change in ({'browser_image': 'latest'}, {'scenario': 'shell'}, {'command': 'rm'}):
            with self.assertRaises(ValueError):
                qa.validate({**CONFIG, **change})

    def test_run_spec_enforces_fresh_temporary_database(self):
        definition = contract()
        definition['files'].append('Dockerfile')
        definition['protected_files'].append('Dockerfile')
        value = {**spec(), 'browser_qa': CONFIG,
                 'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}}
        self.assertEqual(validate(value, definition), value)
        for change in ({'runtime_env': {}}, {'container_port': 9999}):
            with self.assertRaisesRegex(ValueError, 'temporary database'):
                validate({**value, **change}, definition)

    def test_rejects_source_mismatch_before_resources_created(self):
        with patch.object(qa, 'inspect', return_value={'Image': 'sha256:' + 'a' * 64,
                'Id': 'id', 'State': {'Running': True},
                'Config': {'Labels': {'delivery-kit.source-sha': 'b' * 40}}}), \
                patch.object(qa, 'docker') as docker:
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                qa.qualify(config=CONFIG, deployed_container='app', source_sha='a' * 40,
                           evidence_dir='/tmp/not-created', runtime_env={'FEEDBACK_DB_PATH': '/tmp/feedback.db'})
            docker.assert_not_called()

    def test_cleanup_never_removes_unowned_resources(self):
        with patch.object(qa, 'docker') as docker:
            docker.return_value.returncode = 0
            docker.return_value.stdout = json.dumps([{'Config': {'Labels': {}}}])
            with self.assertRaisesRegex(ValueError, 'ownership mismatch'):
                qa.cleanup([('container', 'toso-other-project')], 'owned')
            self.assertEqual(docker.call_count, 1)

    def test_cleanup_timeout_observes_absence_without_repeating_removal(self):
        import subprocess
        present=subprocess.CompletedProcess([],0,json.dumps([{'Id':'owned-id','Config':{'Labels':{'delivery-kit.browser-qa':'owned'}}}]),'')
        absent=subprocess.CompletedProcess([],1,'','Error: No such container: owned-browser')
        healthy=subprocess.CompletedProcess([],0,'28.0','')
        with patch.object(qa,'docker',side_effect=[present,subprocess.TimeoutExpired('docker',30),absent,healthy]) as docker:
            qa.cleanup([('container','owned-browser')],'owned')
        self.assertEqual(sum(call.args[:2]==('container','rm') for call in docker.call_args_list),1)

    def test_cleanup_timeout_does_not_accept_daemon_failure_as_absence(self):
        import subprocess
        present=subprocess.CompletedProcess([],0,json.dumps([{'Id':'owned-id','Config':{'Labels':{'delivery-kit.browser-qa':'owned'}}}]),'')
        unknown=subprocess.CompletedProcess([],1,'','daemon unavailable')
        healthy=subprocess.CompletedProcess([],0,'28.0','')
        with patch.object(qa,'docker',side_effect=[present,subprocess.TimeoutExpired('docker',30),unknown,healthy]):
            with self.assertRaises(ValueError):qa.cleanup([('container','owned-browser')],'owned')

    def test_interrupted_receipt_is_cleaned_but_never_retried(self):
        deployed = {'Image': 'sha256:' + 'a' * 64, 'Id': 'id', 'State': {'Running': True}}
        metadata = {'Config': {'Labels': {'delivery-kit.source-sha': 'a' * 40}}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(qa, 'inspect', side_effect=lambda target, kind='container':
                             deployed if kind == 'container' else metadata), \
                patch.object(qa, 'docker', side_effect=RuntimeError('injected failure')) as docker, \
                patch.object(qa, 'cleanup') as cleanup:
            args = dict(config=CONFIG, deployed_container='app', source_sha='a' * 40,
                        evidence_dir=directory, runtime_env={'FEEDBACK_DB_PATH': '/tmp/feedback.db'})
            with self.assertRaisesRegex(ValueError, 'post-deploy browser QA'):
                qa.qualify(**args)
            count = docker.call_count
            with self.assertRaisesRegex(ValueError, 'previous attempt blocked'):
                qa.qualify(**args)
            self.assertEqual(docker.call_count, count)
            receipt = json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(receipt['status'], 'blocked')
            self.assertEqual(cleanup.call_count, 2)

    def test_metadata_cannot_bypass_automated_qa(self):
        receipt = {'merge_sha': 'a' * 40, 'pr_url': 'pr', 'main_ci_run': 'ci',
                   'deployment': {'url': 'local'}}
        with patch.object(portable_delivery, 'RUN_SPEC', {'browser_qa': CONFIG}), \
                patch.object(portable_delivery, 'cli', return_value={
                    'browser_acceptance': 'passed:' + 'a' * 40}) as client, \
                patch.object(qa, 'qualify', side_effect=ValueError('post-deploy browser QA failed')):
            with self.assertRaisesRegex(ValueError, 'browser QA failed'):
                portable_delivery.publish_board({'issue_id': 'issue'}, receipt)
            self.assertEqual(client.call_count, 1)

    def test_success_is_saved_before_browser_gate_publication(self):
        receipt = {'merge_sha': 'a' * 40, 'pr_url': 'pr', 'main_ci_run': 'ci',
                   'deployment': {'url': 'local'}}
        events = []

        def client(*args, **kwargs):
            events.append(args)
            if args[:2] == ('metadata', 'list'):
                return {'browser_acceptance': 'pending_real_browser'}
            if args[0] == 'get':
                return {'status': 'done'}

        with patch.object(portable_delivery, 'RUN_SPEC', {'browser_qa': CONFIG}), \
                patch.object(portable_delivery, 'cli', side_effect=client), \
                patch.object(portable_delivery, 'save_receipt', side_effect=lambda *a:
                             events.append(('saved',))), \
                patch.object(qa, 'qualify', return_value={'status': 'passed'}):
            portable_delivery.publish_board({'issue_id': 'issue'}, receipt)
        self.assertEqual(events[1], ('saved',))
        self.assertIn('browser_acceptance', events[2])


if __name__ == '__main__':
    unittest.main()
