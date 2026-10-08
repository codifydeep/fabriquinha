import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
import model_proxy as proxy
import test_read_stream_recovery as fixtures
from r3_incident_contract import NAME


class R3ReasonFeedbackTests(unittest.TestCase):
    def test_fixed_installed_probe_is_diagnostic_only(self):
        from r3_reason_probe import run
        proof=run([self.body()['messages'][0]['content'],self.body(True)['messages'][0]['content']])
        self.assertEqual(proof['status'],'r3_reason_transport_qualified')
        self.assertFalse(proof['execution_authorized']);self.assertFalse(proof['worker_tool_executed'])

    def body(self,review=False):
        body=fixtures.request_body()
        note='DELIVERY_PLANNING_START '+'0'*64+'\nSource: 11111111-1111-4111-8111-111111111111\n'
        note+='DELIVERY_R3_INCIDENT_V1:'+('review' if review else 'diagnose')+':'+'a'*64
        note+='\nDELIVERY_R3_FACT:F01\nDELIVERY_R3_FACT:F02'
        if review:note+='\nDELIVERY_R3_PROPOSAL_V1:'+'b'*64
        body['messages'][0]['content']=note
        return body

    def decision(self,review=False):
        value=dict(evidence_sha256='a'*64,reason='Verify the frozen delivery before proposing a conditional resume.',
                   fact_ids=['F01','F02'],execution_authorized=False,release_homologated=False)
        if review:value.update(decision='approve_experiment',proposal_sha256='b'*64)
        else:value.update(action='request_experiment',experiment='verify_frozen_delivery')
        return value

    def wire(self,decision):
        return 200,json.dumps(dict(choices=[dict(message=dict(content=None,tool_calls=[dict(id='call',type='function',
            function=dict(name=NAME,arguments=json.dumps(decision)))]),finish_reason='tool_calls')])).encode(),'application/json'

    def test_single_reason_feedback_preserves_both_diagnosis_and_review_contracts(self):
        for review in (False,True):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                good=self.decision(review);bad=copy.deepcopy(good);bad['reason']='x'*700
                with patch.object(proxy,'forward',side_effect=[self.wire(bad),self.wire(good)]) as forward:
                    response=f.request(self.body(review))
                self.assertEqual(response.status,200);self.assertEqual(forward.call_count,2)
                first,revised=[call.args[0] for call in forward.call_args_list]
                self.assertEqual(first['tools'],revised['tools'])
                feedback=json.loads(revised['messages'][-1]['content'])
                self.assertEqual(feedback['operation'],'format_only_r3_reason_feedback_v1')
                self.assertFalse(feedback['execution_authorized'])
                with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
                    receipt=json.loads(con.execute('SELECT receipt FROM technical_length_feedback').fetchone()[0])
                    self.assertEqual(receipt['operation'],'r3_reason_length_feedback_v1')
                    self.assertEqual(receipt['attempt_limit'],1)
                with patch.object(proxy,'forward') as repeat:
                    self.assertEqual(f.request(self.body(review)).status,502);repeat.assert_not_called()
            finally:f.doCleanups()

    def test_feedback_cannot_change_any_non_reason_field(self):
        for field,value in [('action','retain_hold'),('experiment','none'),('fact_ids',['F02','F01']),
                            ('evidence_sha256','b'*64),('execution_authorized',True)]:
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                bad=self.decision();bad['reason']='x'*700;changed=self.decision();changed[field]=value
                with patch.object(proxy,'forward',side_effect=[self.wire(bad),self.wire(changed)]) as forward:
                    self.assertEqual(f.request(self.body()).status,502)
                self.assertEqual(forward.call_count,2)
            finally:f.doCleanups()

    def test_other_schema_failures_or_extreme_length_are_not_retried(self):
        for field in ('authority','missing','oversized','still_long'):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                bad=self.decision();bad['reason']='x'*700
                if field=='authority':bad['release_homologated']=True
                if field=='missing':del bad['fact_ids']
                if field=='oversized':bad['reason']='x'*4001
                with patch.object(proxy,'forward',return_value=self.wire(bad)) as forward:
                    self.assertEqual(f.request(self.body()).status,502)
                self.assertEqual(forward.call_count,2 if field=='still_long' else 1)
            finally:f.doCleanups()
