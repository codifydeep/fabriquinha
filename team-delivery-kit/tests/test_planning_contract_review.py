import json
import unittest
from planning_contract_review import parse_resolution


class ContractResolutionTests(unittest.TestCase):
    def test_cto_can_choose_either_empty_behavior_without_operator_choice(self):
        for empty in ('all', '400'):
            value = {'parameter': 'status', 'absent': 'all', 'empty': empty,
                     'explicit_all': 'all', 'unknown': '400'}
            self.assertEqual(parse_resolution({'technical_decisions': [json.dumps(value)]}), value)

    def test_unknown_default_or_prose_cannot_become_contract(self):
        for value in ({'parameter': 'status'}, 'Use a sensible default'):
            with self.assertRaises((ValueError, TypeError)):
                parse_resolution({'technical_decisions': [json.dumps(value)]})
        with self.assertRaises(ValueError):
            parse_resolution({'technical_decisions': []})

    def test_flat_cto_contract_has_no_encoded_placeholder(self):
        proposal = {'role': 'cto', 'parameter': 'status', 'absent': 'all',
                    'empty': '400', 'explicit_all': 'all', 'unknown': '400',
                    'reason': 'Reject malformed explicit values while preserving the default.'}
        self.assertEqual(parse_resolution(proposal)['empty'], '400')
        with self.assertRaises(ValueError):
            parse_resolution({**proposal, 'empty': '[REPLACED_MARKER]'})
