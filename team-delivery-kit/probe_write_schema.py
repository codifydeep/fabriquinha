"""One real model tool-argument probe; returned tool calls are never executed."""
import json
import subprocess

from evalctl import PRIVATE, PROJECT
from release_eval import save_receipt
from start_eval import check_model_budget


def main():
    if PROJECT != 'delivery-kit-port2' or check_model_budget()['remaining'] < 65:
        raise ValueError('isolated probe reserve required')
    image = subprocess.check_output(['docker', 'inspect', PROJECT + '-model-proxy-1',
                                    '--format', '{{.Image}}'], text=True).strip()
    script = '''import json,urllib.request
from model_policy import MODEL,PLACEHOLDER_KEY
body={'model':MODEL,'messages':[{'role':'user','content':'Call write_file with path /workspace/probe.py and content # schema probe\\n. Return the tool call only. It will not be executed.'}],
'tools':[{'type':'function','function':{'name':'write_file','parameters':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']}}}],
'tool_choice':{'type':'function','function':{'name':'write_file'}},'max_tokens':256,'stream':False}
req=urllib.request.Request('http://127.0.0.1:8080/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+PLACEHOLDER_KEY,'Content-Type':'application/json'})
response=json.load(urllib.request.urlopen(req,timeout=60))
calls=response['choices'][0]['message'].get('tool_calls',[])
assert len(calls)==1 and calls[0]['function']['name']=='write_file'
args=json.loads(calls[0]['function']['arguments'])
assert set(args)=={'path','content'} and args['path']=='/workspace/probe.py' and isinstance(args['content'],str)
print(json.dumps({'status':'passed','arguments_valid':True,'executed':False}))
'''
    result = json.loads(subprocess.check_output(['docker', 'exec', '-i', '-e', 'PYTHONPATH=/',
        PROJECT + '-model-proxy-1', 'python3', '-c', script], text=True))
    result['proxy_image'] = image
    result['budget_after'] = check_model_budget()
    save_receipt(PRIVATE / 'write-schema-probe.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
