"""Prospective proposal on a verified frozen fixture; never a product retry.

No returned patch executes. Synthetic read frames are explicitly fixture input,
not native tool evidence. A valid proposal cannot prove the historical cause.
"""
import ast
import hashlib
import inspect
import json
from pathlib import PurePosixPath
import re
import uuid
import probe_seed_patch_provider as base


def validate_inputs(value):
    if set(value)!={'issue_id','source_task','manifest_sha256','target','sources','files','context','correction_reason'}:
        raise ValueError('exact controller fixture fields required')
    for key in ('issue_id','source_task'):
        if str(uuid.UUID(value[key]))!=value[key]:raise ValueError('canonical frozen source required')
    if not re.fullmatch('[a-f0-9]{64}',value['manifest_sha256']):raise ValueError('manifest hash required')
    paths=[value['target'],*value['sources']]
    if (not isinstance(value['sources'],list) or not 1<=len(value['sources'])<=4
            or len(set(paths))!=len(paths) or set(value['files'])!=set(paths)
            or not value['target'].startswith('/workspace/tests/test_') or not value['target'].endswith('.py')):
        raise ValueError('bounded distinct source and NEW test paths required')
    for path in paths:
        relative=PurePosixPath(path.removeprefix('/workspace/'))
        if (not path.startswith('/workspace/') or relative.is_absolute() or '..' in relative.parts
                or relative.as_posix()!=path.removeprefix('/workspace/') or not isinstance(value['files'][path],str)
                or not 0<len(value['files'][path].encode())<=65536):raise ValueError('bounded regular code fixture required')
    if sum(len(v.encode()) for v in value['files'].values())>131072:raise ValueError('fixture bytes exceed bound')
    if any(not isinstance(value[k],str) or not 1<=len(value[k])<=limit for k,limit in
            (('context',16000),('correction_reason',1200))):raise ValueError('bounded unchanged context required')


def fixture(model):
    target=INPUT['target']
    prompt=('CONTROLLER DIAGNOSTIC FIXTURE, NOT A PRODUCT TASK. The following source frames come '
        'from a hash-verified frozen snapshot. They are synthetic fixture inputs, NOT executed '
        'read_file calls. Returned patch calls will NOT execute. Propose ONE narrow tests-only '
        'patch following the existing corrective instruction; preserve every assertion and '
        'all product files. Do not return a no-op. This is not proof of historical cause or delivery.\n'
        'Approved context: '+INPUT['context']+'\nExisting correction: '+INPUT['correction_reason']+'\n'
        'DELIVERY_TEST_ARTIFACT_V1:'+target+'\nDELIVERY_TEST_REVISION_V1:'+target+'\n'
        'DELIVERY_SEEDED_EDIT_REQUIRED_V1:'+target+'\n'+
        ''.join('DELIVERY_TEST_SOURCE_V1:'+path+'\n' for path in INPUT['sources']))
    messages=[dict(role='user',content=prompt)]
    for number,path in enumerate([*INPUT['sources'],target]):
        lines=INPUT['files'][path].splitlines()
        for offset in range(0,len(lines),200):
            call=dict(id='diagnostic-fixture-'+str(number)+'-'+str(offset),type='function',
                function=dict(name='read_file',arguments=json.dumps(dict(path=path,offset=offset+1,limit=200))))
            messages.extend([dict(role='assistant',tool_calls=[call]),dict(role='tool',tool_call_id=call['id'],
                content=json.dumps(dict(content='\n'.join(str(i+offset+1)+'|'+line
                    for i,line in enumerate(lines[offset:offset+200])),total_lines=len(lines))))])
    signatures={'read_file':dict(path='string',offset='integer',limit='integer'),
        'write_file':dict(path='string',content='string'),
        'patch':dict(path='string',old_string='string',new_string='string')}
    return dict(model=model,messages=messages,stream=False,max_tokens=8192,
        tools=[dict(type='function',function=dict(name=name,parameters=dict(type='object',
            properties={k:dict(type=v) for k,v in props.items()},required=list(props))))
            for name,props in signatures.items()])


def validate_reply(record):
    import ast
    import model_proxy
    from artifact_response_contract import validate
    body=model_proxy.validate_request(fixture(model_proxy.MODEL))
    if body.get('tool_choice')!=dict(type='function',function=dict(name='patch')):
        raise ValueError('forced diagnostic patch phase required')
    validate(body,json.dumps(record).encode(),'application/json')
    args=json.loads(record['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    source=INPUT['files'][INPUT['target']]
    if source.count(args['old_string'])!=1:raise ValueError('one matching proposed fragment required')
    candidate=source.replace(args['old_string'],args['new_string'],1)
    try:tree=ast.parse(candidate)
    except (SyntaxError,ValueError):raise ValueError('proposed Python syntax rejected') from None
    if len(candidate.encode())>32768:raise ValueError('proposed artifact exceeds file limit')
    def assertions(text):
        return sorted(ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(text))
            if isinstance(n,ast.Assert) or isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                and n.func.attr.startswith('assert'))
    if assertions(source)!=assertions(candidate):raise ValueError('proposed assertions changed')
    return dict(actual_single_patch=True,arguments_valid=True,tools_executed=False,
        proposed_python_syntax_valid=True,proposed_assertions_unchanged=True,
        proposed_candidate_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
        arguments_sha256=hashlib.sha256(json.dumps(args,sort_keys=True).encode()).hexdigest(),
        response_sha256=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest())


def remote_program(identifier,inputs):
    validate_inputs(inputs)
    if str(uuid.UUID(identifier))!=identifier:raise ValueError('canonical diagnostic probe required')
    # Reuse the durable intent, budget reservation and unexecuted transport path.
    source=base.remote_program(identifier).rsplit('\nprint(',1)[0]
    source+='\nINPUT = '+repr(inputs)+'\n'+inspect.getsource(fixture)+'\n'+inspect.getsource(validate_reply)
    source+='\nprint(json.dumps(remote_probe('+repr(identifier)+'),sort_keys=True))\n'
    return source


def main():
    import argparse
    import subprocess
    from pathlib import Path
    from evalctl import PROJECT,PRIVATE
    import docker_grouping
    from release_eval import save_receipt
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--issue',required=True);parser.add_argument('--source',required=True)
    parser.add_argument('--source-file',action='append',required=True)
    args=parser.parse_args()
    if not args.live or PROJECT!='delivery-kit-port2':raise ValueError('explicit isolated diagnostic required')
    for value in (args.issue,args.source):
        if str(uuid.UUID(value))!=value:raise ValueError('canonical blocked source required')
    for name in args.source_file:
        p=PurePosixPath(name)
        if (p.is_absolute() or p.as_posix()!=name or any(part.startswith('.') for part in p.parts)
                or p.suffix not in ('.js','.ts','.tsx','.jsx','.py','.html','.css','.md')):
            raise ValueError('explicit regular source-code path required')
    metadata_script='''import broker as b,native,json,sys
issue,source=sys.argv[1:];settings=json.loads((b.STATE/'native.json').read_text())
with b.db() as c:
 r=c.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? AND source_task=?',(issue,source)).fetchone()
 assert r and r['stage']=='test_first_blocked';d=json.loads(r['data'])
 assert d.get('verified_tool_incident',{}).get('cause_known') is False and d.get('decision',{}).get('action')=='escalate_cto'
 assert not c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
 assert not c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
 route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
 assert route['enabled'] and route['test_first'] and route['author']!=route['cto'] and len(route['test_first_files'])==1
 snapshot=c.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
 assert snapshot and snapshot['status']=='complete'
 parents=[json.loads(r[0]) for r in c.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',(issue,))]
 task=native.task_record(settings,source,route['author']);assert task['status']=='failed'
 parents=[p for p in parents if p.get('test_first_correction_wakeup')==task.get('wakeup_id') and p.get('decision',{}).get('action')=='request_correction']
 assert len(parents)==1
 print(json.dumps(dict(volume=snapshot['volume'],owner=b.OWNER,target=route['test_first_files'][0],
  context=route['execution_context']['description'],correction_reason=parents[0]['decision']['reason'])))
'''
    metadata=json.loads(subprocess.check_output(['docker','exec','-w','/',PROJECT+'-execution-broker-1',
        'python','-c',metadata_script,args.issue,args.source],text=True))
    labels=json.loads(subprocess.check_output(['docker','volume','inspect',metadata['volume'],
        '--format','{{json .Labels}}'],text=True))
    if labels.get('delivery-kit.owner')!=metadata['owner'] or labels.get('delivery-kit.source-task')!=args.source:
        raise ValueError('exact owned frozen volume required')
    paths=[metadata['target'],*args.source_file]
    target=PurePosixPath(metadata['target'])
    if (target.is_absolute() or target.as_posix()!=metadata['target']
            or any(part.startswith('.') for part in target.parts)
            or not metadata['target'].startswith('tests/test_') or target.suffix!='.py'):
        raise ValueError('exact declared regular NEW test required')
    read_script='''import sys,json,hashlib
from pathlib import Path
from r3_snapshot_probe import probe
root=Path('/delivery');manifest=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
inventory=probe(root,manifest);paths=json.loads(sys.argv[1]);files={}
for name in paths:
 path=root/name;assert not path.is_symlink() and path.is_file() and path.stat().st_size<=65536
 files['/workspace/'+name]=path.read_text()
assert sum(len(v.encode()) for v in files.values())<=131072
print(json.dumps(dict(manifest_sha256=manifest,files=files)))
'''
    frozen=json.loads(subprocess.check_output(['docker','run','--rm',
        *docker_grouping.args('frozen-patch-fixture',PROJECT),'--network=none','--read-only',
        '--user','10000:10000','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--memory=256m','--cpus=1','--pids-limit=64','-e','PYTHONPATH=/',
        '--mount','type=volume,source='+metadata['volume']+',target=/delivery,readonly',
        '--entrypoint=python','sha256:3cd0a9b7b96878f81e80463147d78ee69c7c94236bf01c4de43e38a18b083bd1',
        '-c',read_script,json.dumps(paths)],text=True))
    inputs=dict(issue_id=args.issue,source_task=args.source,target='/workspace/'+metadata['target'],
        sources=['/workspace/'+p for p in args.source_file],context=metadata['context'],
        correction_reason=metadata['correction_reason'],**frozen)
    validate_inputs(inputs)
    name=PROJECT+'-model-proxy-1'
    labels=json.loads(subprocess.check_output(['docker','inspect',name,'--format','{{json .Config.Labels}}'],text=True))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='model-proxy':
        raise ValueError('owned isolated proxy required')
    image=subprocess.check_output(['docker','inspect',name,'--format','{{.Image}}'],text=True).strip()
    folder=PRIVATE/'provider-probes';folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink():raise ValueError('restricted private probe directory required')
    intent=folder/('frozen-patch-'+args.source+'.intent.json')
    identity=dict(input_sha256=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest(),
        proxy_image=image,probe_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if intent.exists():
        if intent.is_symlink() or not intent.is_file() or intent.stat().st_mode&0o077:
            raise ValueError('restricted regular intent required')
        old=json.loads(intent.read_text())
        if {k:old[k] for k in identity}!=identity:raise ValueError('frozen diagnostic identity drift')
        identifier=old['execution_id']
    else:
        identifier=str(uuid.uuid4())
        with intent.open('x') as out:json.dump(dict(identity,execution_id=identifier),out)
        intent.chmod(0o600)
    save_receipt(folder/('frozen-patch-'+identifier+'.input.json'),inputs)
    result=json.loads(subprocess.check_output(['docker','exec','-i','-e','PYTHONPATH=/',name,'python','-'],
        input=remote_program(identifier,inputs),text=True))
    if subprocess.check_output(['docker','inspect',name,'--format','{{.Image}}'],text=True).strip()!=image:
        raise ValueError('proxy changed during diagnostic')
    result.update(identity,fixture_kind='frozen_context_prospective_v1',source_task=args.source,
        issue_id=args.issue,manifest_sha256=inputs['manifest_sha256'],native_read_evidence=False,
        candidate_files_written=False)
    receipt=folder/('frozen-patch-'+identifier+'.json')
    if receipt.exists():
        if receipt.is_symlink() or json.loads(receipt.read_text())!=result:raise ValueError('diagnostic receipt drift')
    else:save_receipt(receipt,result)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
