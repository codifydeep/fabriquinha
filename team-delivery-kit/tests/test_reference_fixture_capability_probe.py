import copy
import unittest

import reference_fixture_capability_probe as probe


class ReferenceCapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=probe.run()

    def test_reference_program_executes_missing_behavior_without_editing_candidate(self):
        value=probe.validate(self.result)
        self.assertTrue(all(value['checks'].values()))
        self.assertEqual(value['measurements']['positive']['tests'],3)
        self.assertEqual(value['negative_failure_phases'],{'script':'test_body','markup':'test_body'})
        self.assertTrue(value['synthetic'])
        for field in probe.FALSE_FLAGS:self.assertIs(value[field],False)

    def test_forged_authority_or_changed_source_is_not_capability_evidence(self):
        for mutate in (lambda v:v.update(delivery_approval=True),
                lambda v:v.update(model_calls=1),
                lambda v:v['source_hashes'].update(generic_harness_calibration_v2='0'*64),
                lambda v:v['checks'].update(candidate_bytes_unchanged=False),
                lambda v:v['negative_failure_phases'].update(script='set_up'),
                lambda v:v['measurements']['positive'].update(tests=True)):
            value=copy.deepcopy(self.result);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):probe.validate(value)

    def test_wrong_synthetic_policy_cannot_be_substituted(self):
        value=copy.deepcopy(self.result)
        value['measurements']['policy_sha256']='0'*64
        with self.assertRaises(ValueError):probe.validate(value)
