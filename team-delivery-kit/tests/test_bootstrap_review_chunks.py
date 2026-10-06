import json
import unittest

from bootstrap_review_chunks import parse_chunk


class SplitReviewTests(unittest.TestCase):
    def test_approve_and_change_request_are_structured(self):
        approve = {'role': 'quality_security', 'decision': 'APPROVE',
                   'finding': 'app/server.py reports the exact source SHA.'}
        self.assertEqual(parse_chunk(json.dumps(approve), ('app/server.py',)), approve)
        change = {**approve, 'decision': 'REQUEST_CHANGES',
                  'finding': 'app/server.py contains an unsafe route.'}
        self.assertEqual(parse_chunk(json.dumps(change), ('app/server.py',)), change)
        change['finding'] = 'none'
        with self.assertRaisesRegex(ValueError, 'finding'):
            parse_chunk(json.dumps(change))


if __name__ == '__main__':
    unittest.main()
