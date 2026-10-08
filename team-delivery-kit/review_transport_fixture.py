"""Non-product fixture shared by transport probe and receipt qualification."""
import json


def body():
    sha='a'*64;path='/evidence/candidate/tests/test_fixture.py'
    instruction=('Synthetic protocol fixture only: no file was actually read, no product review is authorized. '
        'Reject this constant-only fixture with one missing_coverage finding at line 3, '
        'test Cases.test_actual, quote self.assertTrue(True).\n'
        'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+sha+'\nDELIVERY_TYPED_REVIEW_V1:'+sha+
        '\nDELIVERY_TEST_FINDINGS_V1\nDELIVERY_OBSERVED_FINDINGS_V1\nDELIVERY_REVIEW_READ_PATH:'+path+'\n')
    return {'messages':[{'role':'user','content':instruction},
        {'role':'assistant','content':None,'tool_calls':[{'id':'synthetic-read','type':'function',
            'function':{'name':'read_file','arguments':json.dumps({'path':path,'offset':1,'limit':100})}}]},
        {'role':'tool','tool_call_id':'synthetic-read','content':json.dumps({'total_lines':3,
            'content':'1|class Cases:\n2|    def test_actual(self):\n3|        self.assertTrue(True)'})}]}
