"""Stdio adapter test using a synthetic controller, not a Multica task."""
import json
from pathlib import Path
import subprocess
from broker_smoke import CONTAINER
from evalctl import process_env

bootstrap = '''import json,os,uuid,urllib.request
from pathlib import Path
request=urllib.request.Request('http://127.0.0.1:8090/v1/grants',data=json.dumps({'task_id':str(uuid.uuid4()),'attempt':1,'mode':'review'}).encode(),headers={'Authorization':'Bearer '+Path('/broker-state/token').read_text(),'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=15) as response:
 os.environ['DELIVERY_EXECUTION_CAPABILITY']=json.load(response)['capability']
'''

if __name__ == '__main__':
    wrapper = Path(__file__).with_name('acp_wrapper.py').read_text()
    frames = [{'jsonrpc': '2.0', 'id': i, 'method': method, 'params': {}}
              for i, method in enumerate(('initialize', 'session/new', 'session/prompt'), 1)]
    result = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-c', bootstrap + '\n' + wrapper],
                            input=''.join(json.dumps(f) + '\n' for f in frames), text=True,
                            capture_output=True, check=True, timeout=90, env=process_env())
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert replies[0]['result']['protocolVersion'] == 1
    assert replies[1]['result']['sessionId']
    assert replies[2]['error']['code'] == -32601
    print('PASS: stdio wrapper -> broker -> sandboxed Hermes; initialize + session/new; prompt denied')
