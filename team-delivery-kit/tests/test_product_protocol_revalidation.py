import copy
import unittest
from planning_intake import parse_proposal, product_protocol_revalidation


class ProductProtocolRevalidationTests(unittest.TestCase):
    def state(self):
        proposal={'role':'product','stories':[{'title':'Product schema response',
             'acceptance':['my response must have role=product. how can I gather requirements?']}],
             'business_questions':['What server architecture should we choose?']}
        return {'stage':'blocked_awaiting_ceo','owner':'ceo','questions':proposal['business_questions'],
            'ceo_answer':{'answer':'Confirmed prior question'},'issues':{'product':'bad'},
            'outputs':{'product':{'task_id':'bad-task','proposal':proposal}}}

    def test_structured_reasoning_is_not_product_acceptance(self):
        import json
        with self.assertRaisesRegex(ValueError,'reasoning'):
            parse_proposal(json.dumps(self.state()['outputs']['product']['proposal']),'product')

    def test_one_bounded_recovery_preserves_rejected_questions_without_answering_them(self):
        state=self.state();before=copy.deepcopy(state)
        result=product_protocol_revalidation(state)
        self.assertEqual(state,before)
        self.assertEqual(result['stage'],'blocked')
        self.assertEqual(result['active'],'product')
        self.assertEqual(result['outputs'],{})
        self.assertEqual(result['ceo_answer'],before['ceo_answer'])
        self.assertEqual(result['rejected_product_protocol']['output'],before['outputs']['product'])
        self.assertEqual(result['rejected_product_protocol']['questions'],before['questions'])
        self.assertNotIn('questions',result)
        result.update(stage='blocked_awaiting_ceo',outputs=before['outputs'],questions=before['questions'])
        self.assertIsNone(product_protocol_revalidation(result))

    def test_real_business_question_is_not_automatically_answered_or_discarded(self):
        state=self.state()
        state['outputs']['product']['proposal']['stories'][0]['title']='Visible service mode'
        state['outputs']['product']['proposal']['stories'][0]['acceptance']=['Indicator shows unavailable']
        self.assertIsNone(product_protocol_revalidation(state))
