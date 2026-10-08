import json
import unittest
from unittest.mock import patch
import model_proxy as proxy
import test_read_stream_recovery as fixtures
import test_r3_reason_feedback as body_fixtures
from r3_incident_contract import NAME


class JsonFeedbackTests(unittest.TestCase):
    def malformed(self,name=NAME):
        return 200,json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':None,
            'tool_calls':[{'id':'bad','type':'function','function':{'name':name,'arguments':'{broken'}}]}}]}).encode(),'application/json'

    def test_malformed_diagnosis_and_review_get_one_fresh_valid_submission_without_mining(self):
        for review in (False,True):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                fixture=body_fixtures.R3ReasonFeedbackTests();body=fixture.body(review);good=fixture.wire(fixture.decision(review))
                with patch.object(proxy,'forward',side_effect=[self.malformed(),good]) as forward:
                    self.assertEqual(f.request(body).status,200)
                self.assertEqual(forward.call_count,2)
                original,revised=[call.args[0] for call in forward.call_args_list]
                self.assertEqual(original['tools'],revised['tools'])
                self.assertNotIn('{broken',json.dumps(revised))
                with patch.object(proxy,'forward') as repeat:
                    self.assertEqual(f.request(fixture.body(review)).status,502);repeat.assert_not_called()
            finally:f.doCleanups()

    def test_wrong_tool_or_second_invalid_submission_remains_rejected(self):
        for mode in ('wrong_tool','malformed','authority'):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                fixture=body_fixtures.R3ReasonFeedbackTests()
                good=fixture.decision(True);good['execution_authorized']=True
                responses=([self.malformed('terminal')] if mode=='wrong_tool' else
                           [self.malformed(),self.malformed() if mode=='malformed' else fixture.wire(good)])
                with patch.object(proxy,'forward',side_effect=responses) as forward:
                    self.assertEqual(f.request(fixture.body(True)).status,502)
                self.assertEqual(forward.call_count,1 if mode=='wrong_tool' else 2)
            finally:f.doCleanups()

    def test_fixed_probe_is_nonexecuting(self):
        from r3_json_probe import run
        proof=run(body_fixtures.R3ReasonFeedbackTests().body(True)['messages'][0]['content'])
        self.assertEqual(proof['status'],'r3_json_transport_qualified')
        self.assertFalse(proof['execution_authorized'])
