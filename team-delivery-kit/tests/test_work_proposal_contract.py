import json
import unittest
from decision_schema import apply
import typed_decision_contract as typed
from structured_response_contract import StructuredResponseRejected


class WorkProposalTests(unittest.TestCase):
    def body(self):
        return typed.apply(apply(dict(messages=[dict(role='user',content='DELIVERY_WORK_PROPOSAL_V1:'+'a'*64+
            '\nDELIVERY_TYPED_WORK_PROPOSAL_V1:'+'a'*64)],tools=[])))
    def value(self):
        return dict(evidence_sha256='a'*64,kind='lifecycle_reconciliation',title='Reconcile existing coverage',
                    reason='Do not manufacture Red.',criteria=['C08','C09','C10'],historical_disposition='preserve_blocked_history',
                    dependency_policy='do_not_release_dependents',product_edit_paths=[],historical_tdd_red=False,
                    release_homologated=False,execution_authorized=False)
    def wire(self,value):
        return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':None,
            'tool_calls':[{'type':'function','function':{'name':typed.NAME,'arguments':json.dumps(value)}}]}}]}).encode()
    def test_exact_values_preserved_without_execution(self):
        out,_,proof=typed.translate(self.body(),self.wire(self.value()),'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),self.value())
        self.assertFalse(proof['worker_tool_executed'])
    def test_new_scope_fake_red_authority_and_duplicate_criteria_rejected(self):
        for key,value in [('kind','new_feature'),('historical_tdd_red',True),('execution_authorized',True),
                          ('criteria',['C08','C08','C10']),('product_edit_paths',['app/static/app.js']),
                          ('evidence_sha256','b'*64),('dependency_policy','release')]:
            with self.assertRaises(StructuredResponseRejected):
                typed.translate(self.body(),self.wire(dict(self.value(),**{key:value})),'application/json')
