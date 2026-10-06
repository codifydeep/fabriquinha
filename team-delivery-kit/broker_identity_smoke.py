"""Exercise controller-issued identities through the deployed offline ACP broker."""
import json
import subprocess
import time
import uuid
from broker_smoke import CONTAINER, wait
from evalctl import process_env

SCRIPT = '''import json,sys,uuid,urllib.request,urllib.error
from pathlib import Path
owner=Path('/broker-state/token').read_text()
def call(path,body,key):
 r=urllib.request.Request('http://127.0.0.1:8090'+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(r,timeout=15) as s:return s.status,json.load(s)
 except urllib.error.HTTPError as e:return e.code,{}
ids=[]
for mode in ('implementation','review'):
 task=str(uuid.uuid4())
 code,grant=call('/v1/grants',dict(task_id=task,attempt=1,mode=mode),owner)
 assert code==200
 key=grant['capability']
 assert call('/v1/grants',dict(task_id=str(uuid.uuid4()),attempt=1,mode=mode),key)[0]==401
 assert call('/v1/acp-probe',{'mode':'implementation'},key)[0]==400
 code,result=call('/v1/acp-probe',{},key)
 assert code==200,(code,result)
 assert call('/v1/acp-probe',{},key)[0]==400
 assert call('/v1/grants',dict(task_id=task,attempt=2,mode=mode),owner)[0]==400
 ids.append(grant['request_id'])
print(json.dumps(ids))
'''


def main():
    ids = json.loads(subprocess.check_output(['docker', 'exec', '-i', CONTAINER, 'python', '-c', SCRIPT],
                                            text=True, timeout=40, env=process_env()))
    for request_id in ids:
        wait(request_id, 'passed', timeout=50)
        name = 'delivery-kit-eval-job-' + request_id
        assert subprocess.run(['docker', 'inspect', name], capture_output=True).returncode != 0
    print(json.dumps({'acp_probe_passed_modes': ['implementation', 'review'],
                      'single_use': True, 'admin_api_denied_to_capability': True,
                      'mode_override_denied': True, 'active_attempt_fenced': True,
                      'model_called': False, 'multica_dispatch_integrated': False}))


if __name__ == '__main__':
    main()
