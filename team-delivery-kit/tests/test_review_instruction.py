import json
import unittest

from review_instruction import bounded


class ReviewInstructionTests(unittest.TestCase):
    def test_over_limit_json_presentation_is_compacted_without_losing_values(self):
        value = {'acceptance': ['Exact body, whitespace inside strings is required.'] * 30}
        text = 'Review ' + json.dumps(value, indent=2) + '\nNever edit; run full suite.'
        result = bounded(text, limit=len(text)-20)
        self.assertEqual(json.loads(result[7:].split('\nNever edit;')[0]), value)
        self.assertTrue(result.endswith('\nNever edit; run full suite.'))

    def test_plain_text_is_never_truncated(self):
        with self.assertRaisesRegex(ValueError, 'route limit'):
            bounded('Acceptance ' + 'x' * 2500)

    def test_short_instructions_remain_byte_identical(self):
        text = 'Review ["literal"] and require Green.'
        self.assertEqual(bounded(text), text)
