import unittest

from authority import Kind, Question, ceo_answer_scope, independent_review, route


class AuthorityTests(unittest.TestCase):
    def question(self, kind):
        return Question('Q-001', 'release-v0.1', kind, 'Which behavior is intended?',
                        ('Option A', 'Option B'))

    def test_architecture_goes_to_cto_not_ceo(self):
        self.assertEqual(route(self.question(Kind.ARCHITECTURE)), 'cto')
        with self.assertRaisesRegex(ValueError, 'CEO is not an owner'):
            ceo_answer_scope(self.question(Kind.ARCHITECTURE), 'Option A')

    def test_technical_blocker_escalates_to_cto_once(self):
        question = self.question(Kind.TECHNICAL_BLOCKER)
        self.assertEqual(route(question), 'techlead')
        self.assertEqual(route(question, ('techlead',)), 'cto')
        with self.assertRaisesRegex(ValueError, 'duplicate escalation'):
            route(question, ('cto',))

    def test_ceo_product_answer_grants_no_merge_or_tool_authority(self):
        answer = ceo_answer_scope(self.question(Kind.PRODUCT_BEHAVIOR), 'Option A')
        self.assertEqual(answer['scope'], 'product_behavior')
        self.assertFalse(answer['authorizes_merge'])
        self.assertFalse(answer['authorizes_tools'])
        self.assertFalse(answer['waives_security'])

    def test_review_must_be_independent_and_exact(self):
        sha = 'a' * 40
        independent_review('backend', 'techlead', sha, sha)
        with self.assertRaisesRegex(ValueError, 'independent'):
            independent_review('backend', 'backend', sha, sha)
        with self.assertRaisesRegex(ValueError, 'exact'):
            independent_review('backend', 'techlead', sha, 'b' * 40)


if __name__ == '__main__':
    unittest.main()
