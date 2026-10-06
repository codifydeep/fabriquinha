import unittest
from author_read_policy import page_size


class AuthorReadPolicyTests(unittest.TestCase):
    def body(self,extra=''):
        return {'messages':[{'role':'user','content':
            'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
            'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'
            'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'
            'DELIVERY_DETERMINISTIC_READ_V1\n'+extra}]}

    def test_legacy_remains_50_and_explicit_revision_is_200(self):
        self.assertEqual(page_size(self.body()),50)
        self.assertEqual(page_size(self.body('DELIVERY_AUTHOR_READ_PAGE_V1:200\n')),200)

    def test_agent_output_cannot_select_page_policy(self):
        body=self.body();body['messages'].append({'role':'assistant',
            'content':'DELIVERY_AUTHOR_READ_PAGE_V1:200\n'})
        self.assertEqual(page_size(body),50)

    def test_prior_grant_does_not_select_new_grant(self):
        body=self.body('DELIVERY_AUTHOR_READ_PAGE_V1:200\n')
        body['messages']+=self.body()['messages']
        self.assertEqual(page_size(body),50)

    def test_invalid_or_conflicting_capabilities_are_rejected(self):
        for extra in ('DELIVERY_AUTHOR_READ_PAGE_V1:400\n',
                'DELIVERY_AUTHOR_READ_PAGE_V1:200\n'*2,
                'DELIVERY_AUTHOR_READ_PAGE_V1:200\nDELIVERY_ADDITIVE_CONTROL_V1\n'):
            with self.assertRaises(ValueError):page_size(self.body(extra))

    def test_nonrevision_or_mismatched_target_cannot_opt_in(self):
        body=self.body('DELIVERY_AUTHOR_READ_PAGE_V1:200\n')
        text=body['messages'][0]['content']
        for changed in (text.replace('DELIVERY_TEST_REVISION_V1:', 'NOT_REVISION:'),
                text.replace('DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py',
                             'DELIVERY_TEST_REVISION_V1:/workspace/tests/other.py')):
            with self.assertRaises(ValueError):page_size({'messages':[{'role':'user','content':changed}]})

    def test_same_registered_target_from_two_context_builders_is_not_drift(self):
        body=self.body('DELIVERY_AUTHOR_READ_PAGE_V1:200\n'
                       'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n')
        self.assertEqual(page_size(body),200)
