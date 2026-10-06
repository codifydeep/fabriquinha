import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
import sort_autonomy_trial as trial
from sort_autonomy_trial import derive,NEW_TEST


class SortAutonomyTests(unittest.TestCase):
    def template(self):
        return json.loads((Path(__file__).resolve().parents[1]/'projects/descartavel2-filter-1-ui.contract.json').read_text())

    def test_old_tests_protected_and_only_two_code_files_editable(self):
        old=self.template();contract,spec=derive(old,old['files'])
        self.assertTrue(set(old['test_files'])<=set(contract['protected_files']))
        self.assertEqual(set(contract['editable_files']),{'app/static/app.js','app/static/index.html',NEW_TEST})
        self.assertEqual(contract['qa_cases'],old['qa_cases'])
        self.assertEqual(contract['test_command'],old['test_command'])
        self.assertEqual(spec['browser_qa']['scenario'],'feedback-board-sort-v1')
        self.assertIn('PHASE 1 TESTS ONLY',spec['description'])

    def test_existing_new_test_or_missing_baseline_rejected(self):
        old=self.template()
        with self.assertRaises(ValueError):derive(old,old['files']+[NEW_TEST])
        with self.assertRaises(ValueError):derive(old,[p for p in old['files'] if p!='tests/test_feedback_filter_client.py'])

    def test_launch_does_not_repeat_dispatch_after_budget_consumption(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'portable-supervisor';path.mkdir()
            receipt={'label':'SORT-1','stage':'supervisor_started_not_delivered','pid':123}
            (path/'SORT-1.launch.json').write_text(json.dumps(receipt))
            with patch.object(trial,'PRIVATE',Path(folder)),patch.object(trial,'PROJECT','delivery-kit-port2'), \
                    patch.object(trial,'prepare') as prepare,patch.object(trial.subprocess,'run') as dispatch:
                self.assertEqual(trial.start(),receipt)
                prepare.assert_not_called();dispatch.assert_not_called()

    def test_controls_require_positive_baseline_and_expected_feature_failure(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(trial,'PRIVATE',Path(folder)), \
                patch('portable_browser_qa.qualify') as qualify:
            qualify.return_value={'status':'failed','cleanup':'passed'}
            with self.assertRaisesRegex(ValueError,'regression'):trial.controls()
            qualify.side_effect=[{'status':'passed','cleanup':'passed'},
                                 {'status':'failed','cleanup':'passed','error':'unrelated failure'}]
            with self.assertRaisesRegex(ValueError,'absent sort'):trial.controls()
