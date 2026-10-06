import json
import unittest
import typed_test_source as t
from artifact_response_contract import validate,ArtifactResponseRejected
from test_artifact_schema import apply

class TypedSourceTests(unittest.TestCase):
    def test_http_handler_restores_stream_requested_by_native_client(self):
        from io import BytesIO
        from unittest.mock import patch
        import model_proxy as p
        body=self.body();wire=json.dumps(dict(stream=True)).encode()
        handler=object.__new__(p.Handler);handler.path='/api/v1/chat/completions'
        handler.headers={'Content-Length':str(len(wire)),'Authorization':p.PLACEHOLDER}
        handler.rfile=BytesIO(wire);handler.wfile=BytesIO();headers={}
        handler.send_response=lambda status:setattr(handler,'test_status',status)
        handler.send_header=lambda key,value:headers.update({key:value})
        handler.end_headers=lambda:None
        source=self.response(['import unittest','class T(unittest.TestCase):',' def test_x(self): assert False'])
        with patch.object(p,'validate_request',return_value=body),patch.object(p,'reserve_call',return_value=1),\
                patch.object(p,'forward',return_value=(200,source,'application/json')),\
                patch.object(p.deterministic_read_dispatch,'make',return_value=None),\
                patch.object(p.typed_decision_contract,'length_feedback_preflight'),\
                patch.object(p.read_stream_recovery,'identity',return_value=None),\
                patch.object(p.read_stream_recovery,'preflight'):
            handler.do_POST()
        self.assertEqual(handler.test_status,200)
        self.assertEqual(headers['Content-Type'],'text/event-stream')
        validate(t.validation_body(body),handler.wfile.getvalue(),'text/event-stream')

    def test_streaming_caller_receives_sse_without_changing_agent_arguments(self):
        body=self.body();lines=['import unittest','class T(unittest.TestCase):',' def test_value(self):','  self.assertEqual(1,2)']
        data,media=t.translate(body,self.response(lines),'application/json')
        streamed,kind=t.caller_response(body,data,media,True)
        self.assertEqual(kind,'text/event-stream')
        self.assertTrue(streamed.endswith(b'data: [DONE]\n\n'))
        validate(t.validation_body(body),streamed,kind)
        frames=[json.loads(line[6:]) for line in streamed.decode().splitlines() if line.startswith('data: {')]
        call=frames[0]['choices'][0]['delta']['tool_calls'][0]
        self.assertEqual(call['id'],'actual-agent-call')
        self.assertEqual(json.loads(call['function']['arguments'])['content'],'\n'.join(lines)+'\n')
        self.assertEqual(frames[-1]['choices'][0]['finish_reason'],'tool_calls')

    def test_nonstreaming_and_unadapted_caller_response_unchanged(self):
        data=b'{}'
        self.assertEqual(t.caller_response({},data,'application/json',True),(data,'application/json'))
        self.assertEqual(t.caller_response(self.body(),data,'application/json',False),(data,'application/json'))

    def body(self):
        return t.apply(apply(dict(messages=[dict(role='user',content='DELIVERY_TYPED_TEST_SOURCE_V1\n'
            'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'),
            dict(role='assistant',tool_calls=[dict(id='read',function=dict(name='read_file',arguments=json.dumps(
                dict(path='/workspace/app.py',offset=1,limit=50))))]),
            dict(role='tool',tool_call_id='read',content=json.dumps(dict(content='1|VALUE = 0',total_lines=1)))],
            tools=[dict(function=dict(name=n,parameters={})) for n in ('read_file','write_file')])))
    def response(self,lines,path='/workspace/tests/test_new.py'):
        return json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[dict(
            id='actual-agent-call',function=dict(name=t.NAME,arguments=json.dumps(dict(path=path,lines=lines))))]))])).encode()
    def test_exact_lines_translate_to_existing_write_then_original_guard(self):
        body=self.body();lines=['import unittest','class T(unittest.TestCase):',' def test_value(self):','  self.assertEqual(1,2)']
        data,media=t.translate(body,self.response(lines),'application/json')
        record=json.loads(data);call=record['choices'][0]['message']['tool_calls'][0]
        self.assertEqual(call['id'],'actual-agent-call');self.assertEqual(call['function']['name'],'write_file')
        self.assertEqual(json.loads(call['function']['arguments'])['content'],'\n'.join(lines)+'\n')
        validate(t.validation_body(body),data,media)
    def test_helper_only_proposal_still_fails_guard(self):
        body=self.body();data,media=t.translate(body,self.response(['def helper(): return 1']),'application/json')
        with self.assertRaises(ArtifactResponseRejected):validate(t.validation_body(body),data,media)
    def test_wrong_path_multiline_or_size_cannot_translate(self):
        body=self.body()
        for lines,path in [(['x'],'/workspace/app.py'),(['import unittest\n#x'],'/workspace/tests/test_new.py'),(['x'*513],'/workspace/tests/test_new.py')]:
            with self.assertRaises(ValueError):t.translate(body,self.response(lines,path),'application/json')
    def test_unmarked_and_read_requests_unaffected(self):
        body={};self.assertIs(t.apply(body),body)
        body=dict(messages=[dict(role='user',content=t.MARKER)],tool_choice=dict(type='function',function=dict(name='read_file')))
        self.assertIs(t.apply(body),body)
