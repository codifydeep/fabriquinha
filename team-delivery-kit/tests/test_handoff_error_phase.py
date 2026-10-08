import unittest
from broker import handoff_runtime


class ErrorPhaseTests(unittest.TestCase):
    def test_repeated_pre_red_error_retains_test_first_owner_protocol(self):
        for stage in ('technical_decision_required', 'test_first_cto_diagnosis', 'diagnose_cto'):
            self.assertEqual(handoff_runtime.error_stage(stage, {'phase':'test_first'}, 'cto', 2),
                             'test_first_blocked')

    def test_first_observation_and_post_red_behavior_are_preserved(self):
        self.assertEqual(handoff_runtime.error_stage('test_first_cto_diagnosis',
                         {'phase':'test_first'}, 'cto', 1), 'test_first_cto_diagnosis')
        self.assertEqual(handoff_runtime.error_stage('awaiting_acceptance',
                         {'target':'cto'}, 'cto', 2), 'technical_decision_required')
        self.assertEqual(handoff_runtime.error_stage('awaiting_acceptance', {}, 'cto', 2), 'diagnose_cto')
