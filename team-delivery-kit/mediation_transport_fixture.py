"""Synthetic mediation fixture, shared by probe and receipt qualification."""
import json


def body():
    path='/evidence/candidate/tests/test_fixture.py'
    instruction=('SYNTHETIC transport fixture only. No product or real artifact is involved. '
        'Return request_review_reconsideration because the cited check exists. '
        'Use exactly one review_disagreement finding, tree candidate, path tests/test_fixture.py, '
        'test Cases.test_actual, line 3, quote self.assertTrue(True). optional_files=[]. '
        'Keep reason short. This cannot approve any delivery.\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'DELIVERY_TYPED_TEST_DIAGNOSIS_V1\nDELIVERY_REVIEW_RECONSIDERATION_V1\n'
        'DELIVERY_TEST_FINDINGS_V1\nDELIVERY_OBSERVED_FINDINGS_V1\nDELIVERY_REVIEW_READ_PATH:'+path+'\n')
    return {'messages':[{'role':'user','content':instruction},
        {'role':'assistant','content':None,'tool_calls':[{'id':'synthetic-read','type':'function',
            'function':{'name':'read_file','arguments':json.dumps({'path':path,'offset':1,'limit':100})}}]},
        {'role':'tool','tool_call_id':'synthetic-read','content':json.dumps({'total_lines':3,
            'content':'1|class Cases:\n2|    def test_actual(self):\n3|        self.assertTrue(True)'})}]}
