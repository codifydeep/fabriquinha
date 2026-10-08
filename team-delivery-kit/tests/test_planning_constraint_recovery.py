import copy
import unittest
from planning_constraint_recovery import revise
from unittest.mock import patch
from planning_constraint_recovery import pending


class ConstraintRecoveryTests(unittest.TestCase):
    def test_supervisor_only_wakes_for_same_configuration_and_verified_recovery(self):
        state={'configuration_sha256':'a'*64}
        with patch('planning_constraint_recovery.observe',return_value={'stage':'schema_recovery_product'}) as observe:
            self.assertFalse(pending(state,'b'*64,{},None))
            observe.assert_not_called()
            self.assertTrue(pending(state,'a'*64,{},None))
        with patch('planning_constraint_recovery.observe',return_value=None):
            self.assertFalse(pending(state,'a'*64,{},None))
    def fixture(self):
        state={'stage':'blocked','active':'product','configuration_sha256':'a'*64,
            'issues':{'product':'issue'},'outputs':{},
            'category':'RuntimeError:planning agent task failed: task'}
        runs=[{'id':'task','status':'failed','agent_id':'agent',
               'failure_reason':'agent_error.provider_server_error'}]
        binding={'task_id':'task','agent_id':'agent','issue_id':'issue',
                 'request_id':'execution','scope':'workspace:agent:planning:task'}
        events=[{'event':'model_proxy_request','execution_id':'execution','status':502,
            'category':'structured_decision_response_invalid','structured_rejection_category':'schema_violation',
            'structured_format':'json_schema','tool_count':0,'call_number':5509}]
        return state,runs,binding,events

    def test_exact_evidence_allows_one_changed_proposal_not_a_delivery(self):
        s,r,b,e=self.fixture();before=copy.deepcopy(s)
        result=revise(s,r,b,e,'agent')
        self.assertEqual(s,before)
        self.assertEqual(result['stage'],'schema_recovery_product')
        self.assertEqual(result['schema_product'],1)
        self.assertEqual(result['outputs'],{})
        self.assertFalse(result['constraint_recovery']['delivery_approved'])
        result.update(stage='blocked')
        self.assertIsNone(revise(result,r,b,e,'agent'))

    def test_other_errors_missing_or_duplicate_evidence_fail_closed(self):
        for where,key,value in [('run','status','completed'),('run','failure_reason','agent_error.other'),
            ('binding','issue_id','other'),('binding','scope','workspace:implementation:task'),
            ('event','execution_id','other'),('event','tool_count',1),
            ('event','structured_rejection_category','nonterminal_or_non_json_response')]:
            s,r,b,e=self.fixture()
            {'run':r[0],'binding':b,'event':e[0]}[where][key]=value
            self.assertIsNone(revise(s,r,b,e,'agent'))
        s,r,b,e=self.fixture()
        self.assertIsNone(revise(s,r,b,[],'agent'))
        self.assertIsNone(revise(s,r,b,e+e,'agent'))
        self.assertIsNone(revise(s,r+r,b,e,'agent'))
