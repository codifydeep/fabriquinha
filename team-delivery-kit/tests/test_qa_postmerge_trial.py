import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qa_postmerge_trial
from qa_postmerge_trial import derive_parent


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = json.loads((ROOT / 'projects/pilot-feedback-board-c2.contract.json').read_text())


class QaPostmergeTrialTests(unittest.TestCase):
    def test_parent_protects_every_existing_test(self):
        tracked = TEMPLATE['files'] + ['tests/test_static_mime.py']
        contract, spec = derive_parent(tracked, TEMPLATE)
        self.assertEqual(spec['label'], 'QAINC-1')
        self.assertEqual(contract['qa_cases'], TEMPLATE['qa_cases'])
        self.assertIn('tests/test_static_mime.py', contract['protected_files'])
        self.assertIn('tests/test_qa_parent_placeholder.py', contract['editable_files'])
        self.assertEqual(set(contract['test_files']) - set(contract['protected_files']),
                         {'tests/test_qa_parent_placeholder.py'})

    def test_refuses_missing_repaired_baseline(self):
        with self.assertRaisesRegex(ValueError, 'repaired feedback board'):
            derive_parent(TEMPLATE['files'], TEMPLATE)

    def test_exact_case_match_fix_reopens_only_its_recorded_escalation(self):
        sha = 'a' * 40
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            status = private / 'autonomy-status' / 'QAINC-1.json'
            status.parent.mkdir()
            status.write_text(json.dumps({
                'label': 'QAINC-1', 'issue_id': 'parent',
                'stage': 'qa_repair_escalation',
                'recovery': {'category': 'ValueError:QA diagnosis retry lacks a precise operator contract'}}))
            incident = {'source_sha': sha, 'parent_issue_id': 'parent',
                        'child_issue_id': 'child',
                        'category': 'post-deploy content type mismatch: /static/app.js'}
            with patch.object(qa_postmerge_trial, 'PRIVATE', private), \
                    patch.object(qa_postmerge_trial, 'find_incident',
                                 return_value=incident):
                result = qa_postmerge_trial.reopen_after_case_match_fix(sha)
            self.assertEqual(result['stage'], 'qa_blocked')
            self.assertEqual(json.loads(status.read_text())['stage'], 'qa_blocked')
            self.assertEqual(json.loads((private / 'qa-fault-trial' /
                              'case-match-reopen.json').read_text())['prior_status']['stage'],
                             'qa_repair_escalation')


if __name__ == '__main__':
    unittest.main()
