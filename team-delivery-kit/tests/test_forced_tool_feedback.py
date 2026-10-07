import copy
from contextlib import redirect_stdout
from io import BytesIO,StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import forced_tool_feedback as feedback
import model_proxy as proxy
from artifact_response_contract import validate,ArtifactResponseRejected

EXEC='11111111-1111-4111-8111-111111111111'

def body():
    return dict(model=proxy.MODEL,stream=False,messages=[dict(role='user',content=
        'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n')],
        tool_choice=dict(type='function',function=dict(name='patch')),tools=[dict(type='function',function=dict(
            name='patch',parameters=dict(type='object',additionalProperties=False,
                required=['path','old_string','new_string'],properties=dict(
                    path=dict(type='string',enum=['/workspace/tests/test_new.py']),
                    old_string=dict(type='string',maxLength=4096),new_string=dict(type='string',maxLength=4096)))))])

def response(count=1):
    call=dict(id='actual-model-call',function=dict(name='patch',arguments=json.dumps(dict(
        path='/workspace/tests/test_new.py',old_string='PRIVATE_OLD',new_string='PRIVATE_NEW'))))
    return json.dumps(dict(choices=[dict(index=0,finish_reason='tool_calls',message=dict(tool_calls=[call]*count))])).encode()

class ForcedFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.counter=Path(self.temp.name)/'calls.json';self.counter.write_text('{"calls":0}')
        self.scope=feedback.identity(body(),EXEC)
    def rejected(self,count=2):
        with self.assertRaises(ArtifactResponseRejected) as raised:validate(body(),response(count),'application/json')
        return raised.exception
    def test_diagnostics_discriminate_multiple_missing_and_incomplete_without_arguments(self):
        error=self.rejected();self.assertEqual(error.diagnostic['tool_calls'],2)
        self.assertTrue(error.diagnostic['stream_complete']);self.assertTrue(error.diagnostic['all_selected_tools'])
        self.assertNotIn('PRIVATE_',json.dumps(error.diagnostic));self.assertEqual(self.rejected(0).diagnostic['tool_calls'],0)
    def test_one_claim_retains_schema_and_never_selects_or_executes_rejected_calls(self):
        original=body();revised=feedback.claim(str(self.counter),self.scope,self.rejected(),original,1)
        self.assertEqual(revised['tools'],original['tools']);self.assertEqual(revised['tool_choice'],original['tool_choice'])
        self.assertEqual(revised['messages'][:-1],original['messages']);self.assertNotIn('PRIVATE_',json.dumps(revised))
        self.assertIsNone(feedback.claim(str(self.counter),self.scope,self.rejected(),original,2))
        feedback.retry_reserved(str(self.counter),self.scope,2);feedback.finish(str(self.counter),self.scope,True)
        feedback.preflight(str(self.counter),self.scope)
        self.assertIsNone(feedback.claim(str(self.counter),self.scope,self.rejected(),original,3))
    def test_crash_claim_blocks_rearming_after_restart(self):
        feedback.claim(str(self.counter),self.scope,self.rejected(),body(),1)
        with self.assertRaises(ValueError):feedback.preflight(str(self.counter),self.scope)
        self.assertIsNone(feedback.claim(str(self.counter),self.scope,self.rejected(),body(),2))
    def test_missing_done_wrong_tools_and_empty_calls_are_not_regenerated(self):
        for change in (dict(stream_complete=False),dict(all_selected_tools=False),dict(tool_calls=0),dict(finish_reason='length')):
            error=self.rejected();error.diagnostic.update(change)
            self.assertIsNone(feedback.claim(str(self.counter),self.scope,error,body(),1))
        self.assertFalse(self.counter.with_name('forced-tool-feedback.sqlite').exists())
    def test_only_exact_new_test_patch_is_eligible(self):
        self.assertIsNotNone(self.scope)
        for path in ('/workspace/app.py','/workspace/tests/../test_new.py','/evidence/test_new.py'):
            candidate=body();candidate['tools'][0]['function']['parameters']['properties']['path']['enum']=[path]
            self.assertIsNone(feedback.identity(candidate,EXEC))
        candidate=body();candidate['tool_choice']['function']['name']='write_file'
        self.assertIsNone(feedback.identity(candidate,EXEC));self.assertIsNone(feedback.identity(body(),None))
    def test_second_retry_reservation_and_symlink_are_rejected(self):
        feedback.claim(str(self.counter),self.scope,self.rejected(),body(),1)
        feedback.retry_reserved(str(self.counter),self.scope,2)
        with self.assertRaises(ValueError):feedback.retry_reserved(str(self.counter),self.scope,3)
        feedback.finish(str(self.counter),self.scope,False)
        with self.assertRaises(ValueError):feedback.preflight(str(self.counter),self.scope)
        self.assertEqual(self.counter.with_name('forced-tool-feedback.sqlite').stat().st_mode&0o777,0o600)
    def request(self):
        wire=json.dumps(body()).encode();h=object.__new__(proxy.Handler)
        h.path='/executions/'+EXEC+'/api/v1/chat/completions';h.headers=dict(Authorization=proxy.PLACEHOLDER)
        h.headers['Content-Length']=str(len(wire));h.rfile=BytesIO(wire);h.wfile=BytesIO()
        h.send_response=lambda status:setattr(h,'status',status);h.send_header=lambda *args:None;h.end_headers=lambda:None
        return h
    def run_handler(self,replies):
        h=self.request()
        with patch.object(proxy,'COUNTER_PATH',str(self.counter)),patch.object(proxy,'validate_request',return_value=body()),\
                patch.object(proxy,'reserve_call',side_effect=[1,2]),patch.object(proxy,'forward',side_effect=replies) as forward,\
                redirect_stdout(StringIO()) as logs:
            h.do_POST()
        self.assertNotIn('PRIVATE_',logs.getvalue());return h,forward
    def test_http_feedback_forwards_only_fully_valid_single_call(self):
        h,forward=self.run_handler([(200,response(2),'application/json'),(200,response(),'application/json')])
        self.assertEqual(h.status,200);self.assertEqual(forward.call_count,2)
        validate(body(),h.wfile.getvalue(),'application/json')
        with feedback.ledger(str(self.counter)) as con:
            self.assertEqual(con.execute('SELECT first_call,retry_call,stage FROM feedback').fetchone(),(1,2,'passed'))
    def test_http_second_invalid_response_is_blocked_without_third_attempt(self):
        h,forward=self.run_handler([(200,response(2),'application/json')]*2)
        self.assertEqual(h.status,502);self.assertEqual(forward.call_count,2)
        self.assertNotIn(b'PRIVATE_',h.wfile.getvalue())
        with self.assertRaises(ValueError):feedback.preflight(str(self.counter),self.scope)
    def test_http_retry_cannot_bypass_original_path_fence(self):
        bad=response().replace(b'/workspace/tests/test_new.py',b'/workspace/app.py')
        h,forward=self.run_handler([(200,response(2),'application/json'),(200,bad,'application/json')])
        self.assertEqual(h.status,502);self.assertEqual(forward.call_count,2)
