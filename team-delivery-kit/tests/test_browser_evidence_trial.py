import hashlib
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import browser_evidence_trial as trial


class BrowserEvidenceTrialTests(unittest.TestCase):
    def test_contract_requalification_requires_specific_failure_and_corrected_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'review-result.json'
            prior={'stage':'blocked_invalid_diagnosis','category':'QA diagnosis requires a bounded root cause',
                   'reads':{'status':'read_evidence_verified'},'task_id':'rejected','issue_id':'prior'}
            path.write_text(json.dumps(prior))
            with patch.object(trial,'FOLDER',Path(folder)),patch.object(trial,'PROJECT','delivery-kit-port2'), \
                    patch.object(trial,'LABEL','BROWSERSPIKE-1'),patch.object(trial.subprocess,'check_output') as inspect:
                inspect.return_value='sha256:f9d7ffc12cd6325a36c5e9919e0eae9da4edd53b2c1d203dc868f645c991f705\n'
                self.assertEqual(trial.contract_review_gate(),prior)
                inspect.return_value='old image'
                with self.assertRaisesRegex(ValueError,'corrected'):trial.contract_review_gate()
                prior['category']='unrelated failure';path.write_text(json.dumps(prior))
                with self.assertRaisesRegex(ValueError,'length rejection'):trial.contract_review_gate()

    def test_contract_review_launch_is_idempotent_without_new_model_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            launch={'stage':'independent_review_started','issue_id':'once'}
            (Path(folder)/'contract-review-launch.json').write_text(json.dumps(launch))
            with patch.object(trial,'FOLDER',Path(folder)),patch.object(trial,'cli') as cli, \
                    patch.object(trial,'read_model_budget') as budget:
                self.assertEqual(trial.review(contract_retry=True),launch)
                cli.assert_not_called();budget.assert_not_called()

    def test_trial_uses_valid_pinned_browser_configuration(self):
        trial.validate({'scenario':'feedback-board-v1','browser_image':trial.BROWSER})

    def fixture(self):
        delivery={'issue_id':trial.PARENT,'merge_sha':trial.SOURCE,
                  'deployment':{'image_id':trial.IMAGE},
                  'delivery':{'source_task':'source','manifest_sha256':'a'*64}}
        receipt={'status':'failed','cleanup':'passed','automated':True,'error':'failure',
                 'identity':{'source_sha':trial.SOURCE,'application_image':trial.IMAGE,
                             'scenario_sha256':hashlib.sha256(b'code').hexdigest()}}
        return delivery,receipt

    def test_real_failed_receipt_bound_to_exact_source_and_scenario(self):
        delivery,receipt=self.fixture()
        with patch.object(trial,'SCRIPT',SimpleNamespace(read_bytes=lambda:b'code')):
            p=trial.payload(delivery,receipt,'card','agent')
        self.assertEqual(p['root_issue_id'],trial.PARENT)
        self.assertEqual(p['source_sha'],trial.SOURCE)
        self.assertEqual(p['read_files'],['app/static/app.js','app/static/index.html'])

    def test_passed_failure_or_script_drift_cannot_be_relabelled(self):
        for field,value in (('status','passed'),('cleanup','failed')):
            delivery,receipt=self.fixture(); receipt[field]=value
            with patch.object(trial,'SCRIPT',SimpleNamespace(read_bytes=lambda:b'code')):
                with self.assertRaises(ValueError):trial.payload(delivery,receipt,'card','agent')
        delivery,receipt=self.fixture()
        with patch.object(trial,'SCRIPT',SimpleNamespace(read_bytes=lambda:b'changed')):
            with self.assertRaises(ValueError):trial.payload(delivery,receipt,'card','agent')

    def test_other_product_image_cannot_be_used_as_historical_source(self):
        delivery,receipt=self.fixture(); receipt['identity']['application_image']='different'
        with patch.object(trial,'SCRIPT',SimpleNamespace(read_bytes=lambda:b'code')):
            with self.assertRaises(ValueError):trial.payload(delivery,receipt,'card','agent')

    def test_review_requires_completed_reads_even_when_diagnosis_format_is_invalid(self):
        with patch.object(trial,'check',return_value={'stage':'blocked_invalid_diagnosis'}), \
                patch.object(trial,'cli') as cli:
            with self.assertRaisesRegex(ValueError,'read-verified'):trial.review()
            cli.assert_not_called()

    def test_unbounded_diagnostic_retry_is_not_supported(self):
        with self.assertRaises(ValueError):trial.select_attempt(4)
