"""Two bounded synthetic provider calls; no returned tools are executed."""
import json
import subprocess

from evalctl import PRIVATE, PROJECT
from release_eval import save_receipt
from start_eval import read_model_budget


def check_call(message, phase):
    calls = message.get('tool_calls') or []
    if len(calls) != 1 or calls[0].get('type') != 'function':
        raise ValueError('one actual tool call required')
    function = calls[0]['function']
    args = json.loads(function['arguments'])
    if phase == 'read':
        if function['name'] != 'read_file' or args != {'path': '/workspace/app.py', 'offset': 1, 'limit': 50}:
            raise ValueError('pinned source read required')
    elif phase == 'write':
        if (function['name'] != 'write_file' or set(args) != {'path', 'content'}
                or args['path'] != '/workspace/tests/test_new.py'
                or not isinstance(args['content'], str) or not 0 < len(args['content'].encode()) <= 32768):
            raise ValueError('nonempty target-bound test required')
    else:
        raise ValueError('unsupported probe phase')
    return calls[0]


def main():
    if PROJECT != 'delivery-kit-port2' or read_model_budget()['remaining'] < 2:
        raise ValueError('isolated two-call probe reserve required')
    image = subprocess.check_output(['docker', 'inspect', PROJECT + '-model-proxy-1',
                                    '--format', '{{.Image}}'], text=True).strip()
    # Code and fixture are synthetic. Neither response nor arguments leave the
    # proxy; only bounded protocol validation and hashes are returned.
    check_source = __import__('inspect').getsource(check_call)
    script = '''import json,urllib.request,urllib.error,hashlib
from pathlib import Path
from model_policy import MODEL,PLACEHOLDER_KEY
''' + check_source + '''
body={'model':MODEL,'messages':[{'role':'user','content':
 'Synthetic tool-routing probe. Read app.py, then return a write_file call containing a small unittest that expects VALUE == 1. Returned calls will NOT execute.\\nDELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\\n'}],
 'tools':[{'type':'function','function':{'name':'read_file','parameters':{'type':'object','properties':{
  'path':{'type':'string'},'offset':{'type':'integer'},'limit':{'type':'integer'}},'required':['path']}}},
  {'type':'function','function':{'name':'write_file','parameters':{'type':'object','properties':{
  'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']}}}],
 'max_tokens':512,'stream':False}
result={'status':'failed','schema':'artifact-provider-probe-v1','model':MODEL,
 'gate_sha256':hashlib.sha256(Path('/test_artifact_schema.py').read_bytes()).hexdigest(),
 'executed':False,'delivery_approval':False,'phases':[]}
for phase in ('read','write'):
 req=urllib.request.Request('http://127.0.0.1:8080/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+PLACEHOLDER_KEY,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=125) as response:
   message=json.load(response)['choices'][0]['message']
  call=check_call(message,phase)
 except urllib.error.HTTPError as error:
  result['failure']={'phase':phase,'http_status':error.code};break
 except (ValueError,KeyError,TypeError):
  result['failure']={'phase':phase,'category':'invalid_tool_protocol'};break
 result['phases'].append({'phase':phase,'arguments_valid':True})
 if phase=='read':
  body['messages'].extend([{'role':'assistant','tool_calls':[call]},
   {'role':'tool','tool_call_id':call['id'],'content':json.dumps({'content':'1|VALUE = 0','total_lines':1})}])
 else:
  result['status']='passed'
print(json.dumps(result))
'''
    result = json.loads(subprocess.check_output(['docker', 'exec', '-i', '-e', 'PYTHONPATH=/',
        PROJECT + '-model-proxy-1', 'python3', '-c', script], text=True))
    result['proxy_image'] = image
    result['budget_after'] = read_model_budget()
    save_receipt(PRIVATE / 'provider-probes' /
                 ('artifact-' + image.removeprefix('sha256:')[:12] + '-' +
                  str(result['budget_after']['calls']) + '.json'), result)
    save_receipt(PRIVATE / 'artifact-provider-probe.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
