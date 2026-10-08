"""Bounded real-provider fixture through the installed proxy; no tool executes.

This is transport evidence, never evidence of product reads, TDD or delivery.
The remote ledger persists intent before the HTTP request and cannot rearm it.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

TARGET='/workspace/tests/test_patch_probe.py'
OLD="QUERY = 'calls.length'"
NEW="QUERY = 'calls.filter(c => c.url === \"/service-mode\").length'"


def rejection_diagnostic(error, raw=None):
    """Allowlisted local evidence: never serialize exception text or proposal bytes."""
    reasons={
        'bounded fixture reply required':'response_size',
        'actual proxy must select the seeded patch phase':'selected_phase',
        'forced diagnostic patch phase required':'selected_phase',
        'exact synthetic replacement required':'exact_replacement',
        'one matching proposed fragment required':'fragment_match',
        'proposed Python syntax rejected':'python_syntax',
        'proposed artifact exceeds file limit':'artifact_size',
        'proposed assertions changed':'assertion_preservation',
        'proposed discovery or assertion execution shape changed':'discovery_preservation',
    }
    reason=reasons.get(str(error),'unclassified_local_validation')
    if isinstance(error,json.JSONDecodeError):reason='response_json'
    result=dict(schema='local-proposal-rejection-v1',constraint=reason,
        exception_type=type(error).__name__ if type(error) in
        (ValueError,KeyError,TypeError,json.JSONDecodeError) else 'Other',
        tools_executed=False,candidate_files_written=False)
    if isinstance(raw,bytes):
        result.update(response_bytes=len(raw),response_sha256=hashlib.sha256(raw).hexdigest())
    return result


def fixture(model):
    prompt=('Synthetic transport fixture: replace exactly '+OLD+' with '+NEW+' using ONE patch call. '
        'Do not change any other bytes or assertions. Returned tools will NOT execute; no product files are available.\n'
        'DELIVERY_TEST_ARTIFACT_V1:'+TARGET+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'
        'DELIVERY_TEST_REVISION_V1:'+TARGET+'\nDELIVERY_SEEDED_EDIT_REQUIRED_V1:'+TARGET+'\n')
    messages=[dict(role='user',content=prompt)]
    content='import unittest\n'+OLD+'\nclass Probe(unittest.TestCase):\n def test_fixture(self): self.assertTrue(QUERY)\n'
    for index,(path,text) in enumerate((('/workspace/app.py','VALUE = 0\n'),(TARGET,content))):
        call=dict(id='synthetic-read-'+str(index),type='function',function=dict(name='read_file',
            arguments=json.dumps(dict(path=path,offset=1,limit=50))))
        messages.extend([dict(role='assistant',tool_calls=[call]),dict(role='tool',tool_call_id=call['id'],
            content=json.dumps(dict(content='\n'.join(str(i)+'|'+line for i,line in enumerate(text.splitlines(),1)),
                total_lines=len(text.splitlines()))))])
    signatures={'read_file':dict(path='string',offset='integer',limit='integer'),
        'write_file':dict(path='string',content='string'),
        'patch':dict(path='string',old_string='string',new_string='string')}
    return dict(model=model,messages=messages,stream=False,max_tokens=1024,
        tools=[dict(type='function',function=dict(name=name,parameters=dict(type='object',
            properties={k:dict(type=v) for k,v in props.items()},required=list(props))))
            for name,props in signatures.items()])


def validate_reply(record):
    from artifact_response_contract import validate
    import model_proxy
    body=model_proxy.validate_request(fixture(model_proxy.MODEL))
    if body.get('tool_choice')!=dict(type='function',function=dict(name='patch')):
        raise ValueError('actual proxy must select the seeded patch phase')
    validate(body,json.dumps(record).encode(),'application/json')
    call=record['choices'][0]['message']['tool_calls'][0]
    args=json.loads(call['function']['arguments'])
    if args!=dict(path=TARGET,old_string=OLD,new_string=NEW):
        raise ValueError('exact synthetic replacement required')
    return dict(actual_single_patch=True,arguments_valid=True,tools_executed=False,
        response_sha256=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest(),
        arguments_sha256=hashlib.sha256(json.dumps(args,sort_keys=True).encode()).hexdigest())


def remote_probe(identifier):
    import model_proxy
    import urllib.request
    import urllib.error
    if str(uuid.UUID(identifier))!=identifier:raise ValueError('canonical probe identity required')
    counter=Path(model_proxy.COUNTER_PATH)
    path=counter.with_name('seed-patch-provider-probes.sqlite')
    if not counter.is_file() or counter.is_symlink() or path.is_symlink():raise ValueError('durable isolated proxy required')
    con=sqlite3.connect(path,timeout=5);path.chmod(0o600)
    try:
        con.execute('PRAGMA synchronous=FULL');con.execute('CREATE TABLE IF NOT EXISTS probes(id TEXT PRIMARY KEY,state TEXT,receipt TEXT)')
        con.commit();con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT state,receipt FROM probes WHERE id=?',(identifier,)).fetchone()
        if row:
            if row[0]=='intent':raise ValueError('probe outcome uncertain; observation only, no repeated request')
            return json.loads(row[1])
        with urllib.request.urlopen('http://127.0.0.1:8080/status',timeout=5) as response:budget=json.load(response)
        if (set(budget)!={'calls','max_calls','remaining'} or any(type(v) is not int or v<0 for v in budget.values())
                or budget['calls']+budget['remaining']!=budget['max_calls'] or budget['remaining']<2):
            raise ValueError('two-call reservation headroom required')
        con.execute('INSERT INTO probes VALUES (?,?,?)',(identifier,'intent',None));con.commit()
        result=dict(operation='real_seed_patch_transport_probe_v1',execution_id=identifier,status='failed',
            model=model_proxy.MODEL,synthetic_fixture=True,tools_executed=False,product_retry=False,
            historical_failure_cause_proven=False,delivery_approval=False,
            budget_before=budget,
            fixture_sha256=hashlib.sha256(json.dumps(fixture(model_proxy.MODEL),sort_keys=True).encode()).hexdigest(),
            validator_sha256=hashlib.sha256(Path('/artifact_response_contract.py').read_bytes()).hexdigest(),
            feedback_sha256=hashlib.sha256(Path('/forced_tool_feedback.py').read_bytes()).hexdigest())
        body=fixture(model_proxy.MODEL)
        request=urllib.request.Request('http://127.0.0.1:8080/executions/'+identifier+'/api/v1/chat/completions',
            data=json.dumps(body).encode(),headers=dict(Authorization=model_proxy.PLACEHOLDER,**{'Content-Type':'application/json'}))
        raw=None
        try:
            with urllib.request.urlopen(request,timeout=250) as response:
                raw=response.read(65537)
                if len(raw)>65536:raise ValueError('bounded fixture reply required')
                record=json.loads(raw)
            result.update(validate_reply(record),status='passed')
        except urllib.error.HTTPError as error:result.update(failure_category='proxy_rejected',http_status=error.code)
        except (TimeoutError,ConnectionError,urllib.error.URLError):result.update(failure_category='transport_observation_failed')
        except (ValueError,KeyError,TypeError) as error:
            result.update(failure_category='fixture_protocol_rejected',
                local_rejection=rejection_diagnostic(error,raw))
        import artifact_rejection_receipts,forced_tool_feedback
        result['rejected_responses']=artifact_rejection_receipts.read(model_proxy.COUNTER_PATH,identifier)
        with forced_tool_feedback.ledger(model_proxy.COUNTER_PATH) as feedback:
            row=feedback.execute('SELECT first_call,retry_call,stage FROM feedback WHERE execution_id=?',(identifier,)).fetchone()
            result['feedback']=dict(first_call=row[0],retry_call=row[1],stage=row[2]) if row else None
        with urllib.request.urlopen('http://127.0.0.1:8080/status',timeout=5) as response:result['budget_after']=json.load(response)
        con.execute('UPDATE probes SET state=?,receipt=? WHERE id=?',(result['status'],json.dumps(result,sort_keys=True),identifier));con.commit()
        return result
    finally:con.close()


def remote_program(identifier):
    if str(uuid.UUID(identifier))!=identifier:raise ValueError('canonical probe identity required')
    source=Path(__file__).read_text().rsplit("\nif __name__ == '__main__':",1)[0]
    return source+'\nprint(json.dumps(remote_probe('+repr(identifier)+'),sort_keys=True))\n'


def main():
    import argparse
    import subprocess
    from evalctl import PRIVATE,PROJECT
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live or PROJECT!='delivery-kit-port2':raise ValueError('explicit isolated live probe required')
    name=PROJECT+'-model-proxy-1'
    before=json.loads(subprocess.check_output(['docker','inspect',name,'--format',
        '{{json .Config.Labels}}'],text=True))
    if before.get('com.docker.compose.project')!=PROJECT or before.get('com.docker.compose.service')!='model-proxy':
        raise ValueError('owned proxy required')
    image=subprocess.check_output(['docker','inspect',name,'--format','{{.Image}}'],text=True).strip()
    folder=PRIVATE/'provider-probes';folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink():raise ValueError('private probe directory required')
    intent=folder/('seed-patch-'+image.removeprefix('sha256:')+'.intent.json')
    if intent.exists():identifier=json.loads(intent.read_text())['execution_id']
    else:
        identifier=str(uuid.uuid4())
        with intent.open('x') as out:json.dump(dict(execution_id=identifier,proxy_image=image),out)
        intent.chmod(0o600)
    source=remote_program(identifier)
    result=json.loads(subprocess.check_output(['docker','exec','-i','-e','PYTHONPATH=/',name,'python','-'],
        input=source,text=True))
    current=subprocess.check_output(['docker','inspect',name,'--format','{{.Image}}'],text=True).strip()
    if current!=image:raise ValueError('proxy changed during probe')
    result['proxy_image']=image
    result['probe_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt=folder/('seed-patch-'+identifier+'.json')
    if receipt.exists():
        if json.loads(receipt.read_text())!=result:raise ValueError('probe receipt drift')
    else:
        with receipt.open('x') as out:json.dump(result,out,sort_keys=True)
        receipt.chmod(0o600)
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
