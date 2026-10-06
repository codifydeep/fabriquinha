"""Two-call synthetic A/B structure probe. Returned tools never execute."""
import inspect
import json
import subprocess
import uuid
from evalctl import PRIVATE,PROJECT
from release_eval import save_receipt
from start_eval import read_model_budget

def probe(variants=('baseline','explicit_raw_source')):
    import ast,json,uuid,urllib.request,urllib.error
    import model_proxy,artifact_rejection_receipts as receipts
    from model_policy import MODEL,PLACEHOLDER_KEY
    from artifact_response_contract import python_structure
    result=dict(schema='artifact-structure-probe-v1',executed=False,red_verified=False,
                delivery_approval=False,cases=[])
    for variant in variants:
        execution=str(uuid.uuid4())
        text=('SYNTHETIC ONLY: app.py contains VALUE=0. Generate a small unittest expecting VALUE==1. '
              'Return the write_file tool call; it will NOT execute.\n'
              'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
              'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\n')
        if variant=='explicit_raw_source':
            text+=('write_file.content must be actual Python source starting with import unittest. '
                   'Define a top-level class extending unittest.TestCase and def test_value(self). '
                   'Use self.assertEqual(app.VALUE,1). The outer function arguments are JSON, '
                   'but the decoded content string is source, NOT a quoted Python string literal, '
                   'JSON envelope, Markdown fence or helper-only harness.\n')
        if variant=='typed_lines':text+='DELIVERY_TYPED_TEST_SOURCE_V1\n'
        body=dict(model=MODEL,max_tokens=2048,stream=False,messages=[dict(role='user',content=text),
            dict(role='assistant',tool_calls=[dict(id='synthetic_read',type='function',function=dict(
                name='read_file',arguments=json.dumps(dict(path='/workspace/app.py',offset=1,limit=50))))]),
            dict(role='tool',tool_call_id='synthetic_read',content=json.dumps(dict(content='1|VALUE = 0',total_lines=1)))],
            tools=[dict(type='function',function=dict(name='read_file',parameters=dict(type='object',
                properties=dict(path=dict(type='string'),offset=dict(type='integer'),limit=dict(type='integer')),
                required=['path','offset','limit']))),
                dict(type='function',function=dict(name='write_file',parameters=dict(type='object',
                properties=dict(path=dict(type='string'),content=dict(type='string')),required=['path','content'])))])
        item=dict(variant=variant,execution_id=execution)
        req=urllib.request.Request('http://127.0.0.1:8080/executions/'+execution+'/api/v1/chat/completions',
            data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+PLACEHOLDER_KEY,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=125) as response:
                message=json.load(response)['choices'][0]['message']
            calls=message.get('tool_calls',[])
            if len(calls)!=1 or calls[0]['function']['name']!='write_file':raise ValueError('wrong tool')
            args=json.loads(calls[0]['function']['arguments'])
            if args.get('path')!='/workspace/tests/test_new.py':raise ValueError('wrong path')
            item.update(status='valid_structure',structure=python_structure(args['content'],ast.parse(args['content'])))
        except urllib.error.HTTPError as error:
            item.update(status='rejected',http_status=error.code,receipts=receipts.read(model_proxy.COUNTER_PATH,execution))
        except (ValueError,KeyError,TypeError):item.update(status='invalid_protocol')
        result['cases'].append(item)
    return result

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-only',action='store_true');parser.add_argument('--typed-only',action='store_true')
    args=parser.parse_args();variants=('typed_lines',) if args.typed_only else ('baseline',) if args.baseline_only else ('baseline','explicit_raw_source')
    if PROJECT!='delivery-kit-port2' or read_model_budget()['remaining']<2:raise ValueError('two-call reserve required')
    source='import json\n'+inspect.getsource(probe)+'\nprint(json.dumps(probe('+repr(variants)+')))\n'
    encoded=subprocess.check_output(['docker','exec','-i','-e','PYTHONPATH=/',PROJECT+'-model-proxy-1',
        'python','-c',source],text=True,timeout=260)
    result=json.loads(encoded);result['budget_after']=read_model_budget()
    image=subprocess.check_output(['docker','inspect',PROJECT+'-model-proxy-1','--format','{{.Image}}'],text=True).strip()
    result['proxy_image']=image
    save_receipt(PRIVATE/'provider-probes'/('structure-'+str(uuid.uuid4())+'.json'),result)
    print(json.dumps(result))

if __name__=='__main__':main()
