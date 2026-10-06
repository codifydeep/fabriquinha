import json
import unittest

from capability_spike import parse_decision


class CapabilitySpikeTests(unittest.TestCase):
    def test_valid_technical_decision(self):
        value = {'role': 'cto', 'decision': 'stdlib_replan',
                 'rationale': 'The offline runtime already includes sqlite3.',
                 'downstream_actions': ['Replan the five blocked cards.']}
        self.assertEqual(parse_decision(json.dumps(value)), value)

    def test_ceo_or_unbounded_output_cannot_make_technical_decision(self):
        value = {'role': 'ceo', 'decision': 'dependency_bundle',
                 'rationale': 'The implementation should use Express.',
                 'downstream_actions': ['Install a reviewed bundle.']}
        with self.assertRaisesRegex(ValueError, 'authority'):
            parse_decision(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'size'):
            parse_decision('x' * 1601)


if __name__ == '__main__':
    unittest.main()
