import copy
import json
import unittest
from unittest.mock import patch
from decision_schema import apply as schema
from typed_decision_contract import apply,translate,claim_length_feedback,length_feedback_preflight
from structured_response_contract import StructuredResponseRejected
import test_typed_decision_contract as td
import technical_optional_files_feedback as feedback


class OptionalFilesFeedbackTests(unittest.TestCase):
    def body(self):
        return apply(schema({'messages':[{'role':'user','content':
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'+feedback.MARKER+'\n'}]}))

    def decision(self):
        return dict(action='request_test_revision',reason='Inspect the recorded failure',optional_files=['tests/test_new.py'])

    def rejection(self,body,decision):
        with self.assertRaises(StructuredResponseRejected) as raised:
            translate(body,td.TypedDecisionTests().wire(decision),'application/json')
        return raised.exception

    def test_reject_first_submission_and_accept_only_model_resubmission_with_empty_files(self):
        body=self.body();before=copy.deepcopy(body);bad=self.decision();error=self.rejection(body,bad)
        self.assertTrue(feedback.enabled(body))
        self.assertEqual(body,before);self.assertFalse(error.receipt['delivery_approval'])
        self.assertTrue(error.length_feedback)
        revised=copy.deepcopy(body);revised['messages'].extend(error.length_feedback)
        fixed={**bad,'optional_files':[]}
        output,_,receipt=translate(revised,td.TypedDecisionTests().wire(fixed),'application/json')
        self.assertEqual(json.loads(json.loads(output)['choices'][0]['message']['content']),fixed)
        self.assertFalse(receipt['worker_tool_executed']);self.assertFalse(receipt['delivery_approval'])
        for drift in ({**fixed,'action':'escalate_cto'},{**fixed,'reason':'Changed hypothesis'}):
            self.rejection(revised,drift)

    def test_never_feedback_for_approval_correction_foreign_schema_or_other_invalid_fields(self):
        for change in ('correction','reason','extra','unknown','foreign','reason_length'):
            body=self.body();bad=self.decision()
            if change=='correction':bad['action']='request_correction'
            if change=='reason':bad['reason']=''
            if change=='extra':bad['approved']=True
            if change=='unknown':bad['action']='approve'
            if change=='foreign':body['tools'][0]['function']['parameters']['properties']['reason']['maxLength']=1201
            if change=='reason_length':bad.update(reason='x'*1300,optional_files=[])
            error=self.rejection(body,bad)
            self.assertFalse(getattr(error,'length_feedback',None),change)

    def test_once_only_persistent_claim_and_proxy_retry_preserve_schema(self):
        import sqlite3
        import model_proxy as proxy
        from test_read_stream_recovery import ReadStreamRecoveryTests,request_body
        fixture=ReadStreamRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        body=self.body();bad=self.decision();fixed={**bad,'optional_files':[]}
        incoming=request_body();incoming['messages']=body['messages']
        with patch.object(proxy,'forward',side_effect=[
                (200,td.TypedDecisionTests().wire(bad),'application/json'),
                (200,td.TypedDecisionTests().wire(fixed),'application/json')]) as forward:
            result=fixture.request(incoming)
        self.assertEqual(result.status,200);self.assertEqual(forward.call_count,2)
        self.assertEqual(forward.call_args_list[0].args[0]['tools'],forward.call_args_list[1].args[0]['tools'])
        with sqlite3.connect(fixture.counter.with_name('deterministic-reads.sqlite')) as c:
            receipt=json.loads(c.execute('SELECT receipt FROM technical_length_feedback').fetchone()[0])
        self.assertEqual(receipt['operation'],'technical_optional_files_feedback_v1')
        self.assertEqual(receipt['attempt_limit'],1)
        self.assertFalse(receipt['delivery_approval'])
        with patch.object(proxy,'forward') as repeat:again=fixture.request(incoming)
        self.assertEqual(again.status,502);repeat.assert_not_called()

    def test_automatic_opt_in_requires_complete_two_tree_reads_and_canonical_schema(self):
        messages=copy.deepcopy(td.TypedDecisionTests().review_body(findings=True,observed=True)['messages'])
        messages[0]['content']=messages[0]['content'].replace(
            'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+'a'*64,'DELIVERY_STRUCTURED_DECISION_V1:technical').replace(
            'DELIVERY_TYPED_REVIEW_V1:'+'a'*64,'DELIVERY_TYPED_DECISION_V1').replace('DELIVERY_TEST_FINDINGS_V1','')
        previous='/evidence/previous/tests/test_new.py'
        messages[0]['content']+='DELIVERY_REVIEW_READ_PATH:'+previous+'\n'
        messages.extend([{'role':'assistant','tool_calls':[{'id':'previous','function':{
            'name':'read_file','arguments':json.dumps({'path':previous})}}]},
            {'role':'tool','tool_call_id':'previous','content':json.dumps({'content':'1|assert value\n','total_lines':1})}])
        body=apply(schema({'messages':messages}))
        candidate=feedback.opt_in(body)
        self.assertTrue(feedback.enabled(candidate))
        self.assertEqual(candidate['tools'],body['tools'])
        self.assertFalse(feedback.enabled(body))
        unread=copy.deepcopy(body);unread['messages']=unread['messages'][:1]
        self.assertIs(feedback.opt_in(unread),unread)
        unmarked=self.body();unmarked['messages'][0]['content']=unmarked['messages'][0]['content'].replace(feedback.MARKER,'')
        self.assertFalse(feedback.enabled(unmarked))

    def test_cap_and_repeated_invalid_submission_never_allow_third_call(self):
        import model_proxy as proxy
        from test_read_stream_recovery import ReadStreamRecoveryTests,request_body
        for cap,status,calls in ((1,400,1),(2,502,2)):
            fixture=ReadStreamRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
            incoming=request_body();incoming['messages']=self.body()['messages']
            bad=td.TypedDecisionTests().wire(self.decision())
            with patch.object(proxy,'MAX_CALLS',cap),patch.object(proxy,'forward',return_value=(200,bad,'application/json')) as forward:
                result=fixture.request(incoming)
            self.assertEqual(result.status,status)
            self.assertEqual(forward.call_count,calls)
            self.assertEqual(proxy.load_calls(),calls)
            fixture.doCleanups()
