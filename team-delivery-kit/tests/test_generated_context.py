import unittest
from generated_context import compact, START, END


class GeneratedContextTests(unittest.TestCase):
    def test_only_known_controller_policy_is_represented_more_compactly(self):
        head = 'Acceptance literal.\nApproved CEO request: ' + 'x'*3300 + '\nBinding CTO proposal: exact architecture\n'
        text = head + START + '["test_new.py"]' + END + '\nDELIVERY_TYPED_TEST_SOURCE_V1\n'
        result, proof = compact(text)
        self.assertTrue(result.startswith(head))
        self.assertTrue(result.endswith('\nDELIVERY_TYPED_TEST_SOURCE_V1\n'))
        self.assertIn('test_new.py', result)
        self.assertLess(len(result), len(text))
        self.assertIs(proof['delivery_approval'], False)

    def test_unknown_policy_and_arbitrary_large_text_are_not_silently_changed(self):
        text = 'x'*4222
        self.assertEqual(compact(text), (text, None))
        head = '\nApproved CEO request: ' + 'x'*4000 + '\nBinding CTO proposal: exact\n'
        text = head+START+'["test_new.py"]'+END+' unauthorized policy'
        self.assertEqual(compact(text), (text, None))
