import json
import unittest

from bootstrap_review import parse_review


class BootstrapReviewTests(unittest.TestCase):
    def test_independent_approval_schema(self):
        value = {'role': 'quality_security', 'decision': 'APPROVE',
                 'findings': [], 'rationale': 'The baseline test is preserved.'}
        self.assertEqual(parse_review(json.dumps(value)), value)

    def test_change_request_needs_concrete_finding(self):
        value = {'role': 'quality_security', 'decision': 'REQUEST_CHANGES',
                 'findings': [], 'rationale': 'A concrete problem exists.'}
        with self.assertRaisesRegex(ValueError, 'finding'):
            parse_review(json.dumps(value))
        value['role'] = 'techlead'
        with self.assertRaisesRegex(ValueError, 'identity'):
            parse_review(json.dumps(value))


if __name__ == '__main__':
    unittest.main()
