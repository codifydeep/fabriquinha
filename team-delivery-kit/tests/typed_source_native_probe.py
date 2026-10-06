"""Offline native SDK/consumer/tool qualification, not a model delivery."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    import typed_test_source as transport
    from artifact_response_contract import validate
    from openai import OpenAI
    from agent.auxiliary_client import _aggregate_chat_stream

    root=Path('/workspace');(root/'tests').mkdir(parents=True)
    baseline=root/'app.py';baseline.write_text('VALUE = 0\n');baseline.chmod(0o444)
    target=root/'tests/test_new.py';target.write_text('');target.chmod(0o666)
    (root/'tests').chmod(0o555);root.chmod(0o555)
    old_hash=hashlib.sha256(baseline.read_bytes()).hexdigest()
    lines=['import unittest, app','class New(unittest.TestCase):',
           ' def test_value(self):','  self.assertEqual(app.VALUE, 1)']
    body={'tool_choice':{'type':'function','function':{'name':transport.NAME}},
          'tools':[{'function':{'name':transport.NAME,'parameters':{'properties':{'path':{'enum':[str(target)]}}}}},
                   {'function':{'name':'write_file','parameters':{'required':['path','content'],
                    'properties':{'path':{'type':'string','enum':[str(target)]},'content':{'type':'string','maxLength':6144}}}}}],
          'messages':[{'role':'user','content':'DELIVERY_TEST_ARTIFACT_V1:'+str(target)}]}
    proposed=json.dumps({'id':'offline-native-proposal','created':0,'model':'offline-fixture',
        'object':'chat.completion','choices':[{'index':0,'finish_reason':'tool_calls',
         'message':{'role':'assistant','tool_calls':[{'id':'actual-fixture-call','type':'function',
          'function':{'name':transport.NAME,'arguments':json.dumps({'path':str(target),'lines':lines})}}]}}]}).encode()
    data,media=transport.translate(body,proposed,'application/json')
    validate(transport.validation_body(body),data,media)
    stream,kind=transport.caller_response(body,data,media,True)
    validate(transport.validation_body(body),stream,kind)

    class Fixture(BaseHTTPRequestHandler):
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert request['stream'] is True
            output,content_type=(data,media) if self.path.endswith('/broken/chat/completions') else (stream,kind)
            self.send_response(200);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(output)));self.end_headers();self.wfile.write(output)
        def log_message(self,*args):pass

    # Loopback only in --network none; no provider/key/socket or product source.
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def consume(route):
        with OpenAI(base_url='http://127.0.0.1:'+str(server.server_port)+route,
                    api_key='offline-placeholder',max_retries=0,timeout=5) as client:
            chunks=client.chat.completions.create(model='offline-fixture',messages=[{'role':'user','content':'fixture'}],stream=True)
            return _aggregate_chat_stream(chunks,model='offline-fixture',total_ceiling=5)
    try:
        try:
            broken=consume('/broken')
            broken_calls=broken.choices[0].message.tool_calls or []
        except (ValueError,IndexError,RuntimeError):broken_calls=[]
        assert not broken_calls,'JSON response unexpectedly consumable as native SSE'
        actual=consume('/fixed');calls=actual.choices[0].message.tool_calls
        assert len(calls)==1 and calls[0].id=='actual-fixture-call'
        assert calls[0].function.name=='write_file'
        args=json.loads(calls[0].function.arguments)
        assert args=={'path':str(target),'content':'\n'.join(lines)+'\n'}
        os.setgroups([]);os.setgid(10000);os.setuid(10000)
        os.environ['HERMES_FENCED_INPLACE_WRITES']='1'
        os.environ['HERMES_WRITE_SAFE_ROOT']=str(root)
        from tools.file_tools import write_file_tool
        receipt=json.loads(write_file_tool(**args))
        assert receipt.get('verified') is True and not receipt.get('error'), 'offline fixture write rejected: '+str(receipt.get('error'))[:250]
        assert target.read_text()==args['content']
        denied=json.loads(write_file_tool(str(baseline),'VALUE = 1\n'))
        assert denied.get('error') and hashlib.sha256(baseline.read_bytes()).hexdigest()==old_hash
        suite=subprocess.run(['python3','-m','unittest','discover','-s','tests','-q'],
                             cwd=root,capture_output=True,text=True)
        assert suite.returncode==1 and 'FAIL: test_value' in suite.stderr and 'ERROR:' not in suite.stderr
        print(json.dumps(dict(schema='typed-source-native-offline-v1',status='passed',
            broken_transport_has_no_tool_calls=True,fixed_transport_call_preserved=True,
            native_hermes_write_verified=True,protected_write_denied=True,
            baseline_hash_unchanged=True,fixture_red_exit_code=suite.returncode,
            model_calls=0,model_authorship=False,delivery_approval=False)))
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()
