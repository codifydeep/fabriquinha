import copy
import unittest
from broker.request_scope_replan import failed_experiment_handoff


class FailedExperimentHandoffTests(unittest.TestCase):
    def setUp(self):
        self.data = {'artifact_diagnosis': True, 'validation_failure': {'category': 'executed_test_failure'},
                     'phase_evidence': {'red_manifest': 'original'}, 'wakeup_id': 'old', 'decision': {'action': 'request_test_revision'}}
        self.state = {'stage': 'blocked', 'container_id': 'c'*64, 'exit_code': 1, 'output_sha256': 'a'*64}

    def test_one_diagnostic_preserves_red_without_test_or_author_authority(self):
        original = copy.deepcopy(self.data)
        result = failed_experiment_handoff(self.data, self.state, 'peer')
        self.assertEqual(self.data, original)
        self.assertEqual(result['phase_evidence'], original['phase_evidence'])
        self.assertEqual(result['trigger_task'], 'peer')
        self.assertNotIn('wakeup_id', result); self.assertNotIn('decision', result)
        proof = result['unsupported_experiment_recovery']
        self.assertEqual(proof['cause'], 'unknown'); self.assertEqual(proof['attempt_limit'], 1)
        self.assertFalse(proof['test_edits_authorized']); self.assertFalse(proof['delivery_approval'])
        self.assertFalse(proof['author_restarted'])
        with self.assertRaises(ValueError): failed_experiment_handoff(result, self.state, 'peer')

    def test_no_restart_on_observation_delay_or_success(self):
        for field, value in [('stage', 'start_intent'), ('exit_code', 0), ('exit_code', None), ('container_id', '')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                failed_experiment_handoff(self.data, {**self.state, field: value}, 'peer')
        with self.assertRaises(ValueError):
            failed_experiment_handoff({**self.data, 'artifact_diagnosis': False}, self.state, 'peer')

    def test_unrelated_recipe_failure_is_not_product_or_test_evidence(self):
        data = copy.deepcopy(self.data)
        data['validation_failure'].update(
            diagnostic_read_files=['tests/test_feedback_latest_ui.py'],
            failures=[{'qualified_name': 'tests.test_feedback_latest_ui.Client.test_poll'}])
        result = failed_experiment_handoff(data, self.state, 'peer')
        proof = result['unsupported_experiment_recovery']
        self.assertEqual(proof['cause'], 'recipe_scope_mismatch')
        self.assertFalse(proof['causal_evidence_for_delivery'])
        self.assertEqual(len(proof['failure_sha256']), 64)
        self.assertFalse(proof['test_edits_authorized'])
        self.assertFalse(proof['author_restarted'])
        self.assertEqual(result['phase_evidence'], data['phase_evidence'])
        self.assertIn('independently reviewed', result['required_action'])

    def test_missing_or_shared_scope_metadata_does_not_infer_mismatch(self):
        for names, paths in [([], ['tests/other.py']),
                             (['tests.test_service_mode_indicator.Client.test_poll'], ['tests/other.py']),
                             (['tests.other.Client.test_poll'], ['tests/test_service_mode_indicator.py'])]:
            data = copy.deepcopy(self.data)
            data['validation_failure'].update(diagnostic_read_files=paths,
                failures=[{'qualified_name': n} for n in names])
            self.assertEqual(failed_experiment_handoff(data, self.state, 'peer')
                ['unsupported_experiment_recovery']['cause'], 'unknown')
