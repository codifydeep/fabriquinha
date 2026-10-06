"""Live Hermes round trips via broker, not native Multica dispatch."""
import subprocess
from broker_smoke import CONTAINER
from evalctl import process_env

CLIENT = '''import json,uuid,urllib.request,urllib.error
from pathlib import Path
def call(path,body,key):
 r=urllib.request.Request('http://127.0.0.1:8090'+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(r,timeout=30) as s:return s.status,json.load(s)
 except urllib.error.HTTPError as e:return e.code,{}
owner=Path('/broker-state/token').read_text()
code,grant=call('/v1/grants',dict(task_id=str(uuid.uuid4()),attempt=1,mode='review'),owner)
assert code==200
key=grant['capability']
assert call('/v1/acp-open',{},key)[0]==200
try:
 def frame(i,method,params):return {'frame':{'jsonrpc':'2.0','id':i,'method':method,'params':params}}
 code,result=call('/v1/acp-message',frame(1,'initialize',{'clientCapabilities':{'terminal':True}}),key)
 assert code==200 and result.get('result',{}).get('protocolVersion')==1,(code,result)
 assert call('/v1/acp-message',frame(2,'session/prompt',{}),key)[0]==400
 assert call('/v1/acp-message',frame(3,'session/resume',{}),key)[0]==400
 code,session=call('/v1/acp-message',frame(4,'session/new',{'cwd':'/broker-state','mcpServers':[{'name':'forbidden','command':'sh'}]}),key)
 assert code==200,(code,session)
 assert 'sessionId' in session.get('result',{}),'Hermes session creation failed'
 print(json.dumps({'initialize_passed':True,'prompt_denied':True,'resume_denied':True,'session_created':'sessionId' in session.get('result',{}),'session_error_code':session.get('error',{}).get('code'),'diagnostic':session.get('error',{}).get('data',{}),'model_called':False,'native_dispatch':False}))
finally:
 assert call('/v1/acp-close',{},key)[0]==200
assert call('/v1/acp-message',frame(5,'initialize',{}),key)[0]==400
print('PASS: closed capability cannot reopen the stream')
'''

if __name__ == '__main__':
    subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-c', CLIENT],
                   env=process_env(), check=True, timeout=100)
