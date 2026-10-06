import copy
import json
from pathlib import Path
import unittest

from kit_contract import validate

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'team.example.json').read_text())

    def test_example_valid(self):
        self.assertEqual(validate(self.config), [])

    def test_new_role_needs_no_engine_change(self):
        role = copy.deepcopy(self.config['roles']['backend_data'])
        role['responsibilities'] = ['Assess accessibility and report evidence']
        self.config['roles']['accessibility_specialist'] = role
        self.assertEqual(validate(self.config), [])

    def test_self_review_rejected(self):
        self.config['roles']['backend_data']['reviewer'] = 'backend_data'
        self.assertTrue(validate(self.config))

    def test_unknown_escalation_rejected(self):
        self.config['roles']['frontend']['escalates_to'] = 'missing'
        self.assertTrue(validate(self.config))

    def test_disabled_reviewer_rejected(self):
        self.config['roles']['frontend']['reviewer'] = 'product_analyst'
        self.assertTrue(validate(self.config))

    def test_capacity_bound(self):
        self.config['execution']['max_workers'] = 3
        self.assertTrue(validate(self.config))

    def test_observability_is_assessed_not_mandatory_emission(self):
        self.assertTrue(self.config['quality']['instrumentation_assessment_required'])
        self.assertFalse(self.config['roles']['product_analyst']['enabled'])
        self.assertFalse(self.config['roles']['observability_engineer']['enabled'])

    def test_credential_inline_rejected(self):
        self.config['openrouter_api_key'] = 'never-store-a-secret-here'
        self.assertTrue(validate(self.config))

    def test_project_changes_without_core_changes(self):
        self.config['project']['repository'] = 'https://github.com/example-org/second-demo'
        self.config['project']['test_commands'] = [['pytest', '-q']]
        self.assertEqual(validate(self.config), [])

    def test_command_string_rejected(self):
        self.config['project']['test_commands'] = ['npm test; echo bad']
        self.assertTrue(validate(self.config))

    def test_guard_cannot_be_disabled(self):
        self.config['quality']['immutable_review'] = False
        self.assertTrue(validate(self.config))

    def test_unknown_fields_not_silently_accepted(self):
        self.config['quality']['disable_review'] = True
        self.assertTrue(validate(self.config))


if __name__ == '__main__':
    unittest.main()
