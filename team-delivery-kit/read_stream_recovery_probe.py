"""Disposable real-HTTP recovery canary; synthetic upstream, no model credentials."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import urllib.request
import urllib.error
from unittest.mock import patch

import model_proxy as proxy
import read_stream_recovery as recovery


def run():
    body={'model':proxy.MODEL,'stream':True,'messages':[{'role':'user','content':
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_REVIEW_READ_PATH:/evidence/candidate/app.py\n'}],
        'tools':[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]}
    first='11111111-1111-4111-8111-111111111111';second='22222222-2222-4222-8222-222222222222'
    args={'path':'/evidence/candidate/app.py','offset':1,'limit':100}
    frame={'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{
        'name':'read_file','arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}]}
    good=(200,('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n').encode(),'text/event-stream')
    error=(200,b'data: {"error":{"message":"synthetic-secret-do-not-forward"}}\n\ndata: [DONE]\n','text/event-stream')
    with tempfile.TemporaryDirectory() as directory:
        counter=Path(directory)/'calls.json';counter.write_text('{"calls":0}')
        def request(server,execution):
            r=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/executions/'+execution+'/api/v1/chat/completions',
                data=json.dumps(body).encode(),headers={'Authorization':proxy.PLACEHOLDER,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(r,timeout=10) as reply:status,data=reply.status,reply.read()
            except urllib.error.HTTPError as reply:status,data=reply.code,reply.read()
            assert b'synthetic-secret-do-not-forward' not in data
            return status
        def serve():
            server=proxy.ThreadingHTTPServer(('127.0.0.1',0),proxy.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            return server,thread
        def stop(server,thread):server.shutdown();server.server_close();thread.join(timeout=5);assert not thread.is_alive()
        with patch.object(proxy,'COUNTER_PATH',str(counter)),patch.object(proxy,'MAX_CALLS',4),\
                patch.object(proxy,'CALLS',0),patch.object(proxy,'PROVIDER_PAUSE',None),\
                patch.object(proxy,'forward',side_effect=[error,good,error,error]) as forward,redirect_stdout(StringIO()):
            server,thread=serve()
            try:
                passed=request(server,first)==200
                blocked=request(server,second)==502
                replay_blocked=request(server,second)==400
            finally:stop(server,thread)
            proxy.CALLS=proxy.load_calls()
            server,thread=serve()
            try:restart_blocked=request(server,second)==400
            finally:stop(server,thread)
            assert forward.call_count==4 and proxy.load_calls()==4
        fixed=proxy.validate_request(body)
        scope=recovery.identity(fixed,second)
        script='''import json,sys,read_stream_recovery as r
p=json.load(sys.stdin)
try:r.preflight(p['counter'],p['scope']);blocked=False
except ValueError:blocked=True
print(json.dumps({'blocked':blocked}))
'''
        child=subprocess.run(['python3','-c',script],input=json.dumps({'counter':str(counter),'scope':scope}),
                             text=True,capture_output=True,timeout=10,
                             env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parent)})
        child_blocked=child.returncode==0 and json.loads(child.stdout)['blocked'] is True
        with recovery.connect(str(counter)) as con:
            rows=con.execute('SELECT first_call,retry_call,stage FROM recovery ORDER BY first_call').fetchall()
        no_payload=(counter.with_name('read-stream-recovery.sqlite').read_bytes().find(b'/evidence/candidate/app.py')==-1)
        no_write=recovery.identity({**fixed,'tool_choice':{'type':'function','function':{'name':'write_file'}}},first) is None
        good_identity=(rows==[(1,2,'passed'),(3,4,'blocked')])
        success=all((passed,blocked,replay_blocked,restart_blocked,child_blocked,no_payload,no_write,good_identity))
        return {'schema':'read-stream-recovery-probe-v1','status':'passed' if success else 'failed',
            'transport':'real-http-synthetic-upstream','single_retry_verified':good_identity,
            'valid_response_only':passed,'repeated_failure_blocked':blocked and replay_blocked,
            'restart_blocked':restart_blocked and child_blocked,'durable_calls':4,'real_model_calls':0,
            'write_retry_forbidden':no_write,'payload_absent':no_payload,'delivery_approval':False,'product_retry':False}


if __name__=='__main__':print(json.dumps(run()))
