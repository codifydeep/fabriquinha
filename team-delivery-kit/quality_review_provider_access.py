"""Operator-only payment resolution/registration; never an agent or model call.

Requires explicit human confirmation. Resolve runs only in the SAME already
running proxy under sealed idle maintenance. The operator stops that exact proxy
before registration. Lost effects have separate observation actions; they are
never resubmitted. Receipt/log archives are private and no delivery gate is waived.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import hashlib
import quality_provider_resolution as contract
from install_quality_preview import inspect,save
from migrate_quality_candidate_pin import read,folder
from qualify_quality_red_observer import require_idle
from quality_candidate_authority import Authority
from recover_quality_review_completion import qualification
from qualify_quality_provider_access import qualify as payment_runtime

ROOT=Path(__file__).resolve().parent
SOURCE='''import sys,json;sys.path.insert(0,"/")
import broker as b,native,quality_test_review as review,quality_review_attestation as attest
source,previous=sys.argv[1:]
c,s=review.load(b,source);settings=json.loads((b.STATE/"native.json").read_bytes())
t=native.task_record(settings,previous,c["reviewer"]);a=attest.load(b,source)
assert s["stage"]=="admitted" and s["review_task"]==previous and t["status"]=="failed"
assert a and a["stage"]=="technical_blocked" and a["request_id"]==s["request_id"]
print(json.dumps(dict(request_id=s["request_id"])))
'''
REGISTER='''import sys,json;sys.path.insert(0,"/")
import broker as b,quality_review_completion_recovery as recovery
p=json.loads(sys.stdin.read(65537))
if sys.argv[1]=="observe":
 rows=[r for r in recovery.records(b,p["source_task"]) if r["previous_task"]==p["previous_task"]]
 assert len(rows)<=1
 r=rows[0] if rows else None
 if r:assert r["request"]==p
else:r=recovery.register(b,p["source_task"],p["previous_task"],p["maintenance_operation"],
 qualified=p["qualification"],provider_resolution=p["provider_resolution"],runtime_identity=p["runtime_identity"])
print(json.dumps(dict(stage="registered" if r else "not_observed",incident_closed=False,
 tests_approved=False,delivery_approval=False,model_calls=0,
 marker=r["new_marker"] if r else None)))
'''


def archive(namespace,operation):
    contract.require(isinstance(namespace,str) and re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace))
    contract.canonical(operation)
    private=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))
    # Do not create another installation as a side effect of a recovery.
    contract.require(private.is_dir())
    folder(private);folder(private/'backups')
    return folder(private/'backups'/('quality-review-payment-'+operation))


def event_from_logs(text,request):
    contract.require(isinstance(text,str) and len(text.encode())<=16777216)
    events=[]
    for line in text.splitlines():
        try:item=json.loads(line if line.startswith('{') else line.partition(' ')[2])
        except ValueError:continue
        if isinstance(item,dict) and item.get('event')=='model_proxy_request' and item.get('execution_id')==request:
            events.append(item)
    found=[e for e in events if e.get('status')==402 and e.get('call_number') is not None]
    contract.require(len(found)==1)
    selected={k:found[0][k] for k in contract.EVENT_KEYS}
    contract.event(selected,request)
    contract.require(not any(e.get('status')==200 and e.get('started_at',0)>=selected['started_at'] for e in events))
    return selected


def same_proxy(namespace,proxy):
    config=proxy.get('Config') or {};labels=config.get('Labels') or {}
    contract.require(proxy.get('Name')=='/'+namespace+'-model-proxy-1' and config.get('User')=='10000:10000'
        and labels.get('com.docker.compose.project')==namespace and labels.get('com.docker.compose.service')=='model-proxy')
    return {key:proxy.get(key) for key in ('Id','Image','Name','Config','HostConfig','Mounts')}


def effect(command,*,input=None,timeout=55):
    return subprocess.run(command,input=input,text=True,capture_output=True,timeout=timeout)


def resolve(namespace,image,source,previous,operation,*,confirmed=False,observe=False,finish=False):
    # Check human intent BEFORE Docker, keys, HTTP, directory creation or writes.
    contract.require(confirmed is True and type(observe) is bool and type(finish) is bool and not (observe and finish))
    for value in (source,previous,operation):contract.canonical(value)
    authority=Authority(namespace,image);authority.inspect_controller()
    held,_=require_idle(namespace);contract.require(held['operation_id']==operation)
    directory=archive(namespace,operation);statefile=directory/'resolution-state.json'
    identity=dict(namespace=namespace,image=image,source=source,previous=previous,operation=operation,
        resolver_sha256=contract.source_sha256())
    proxy=inspect(namespace+'-model-proxy-1');metadata=same_proxy(namespace,proxy)
    if statefile.exists():
        state=json.loads(read(statefile));contract.require(state['identity']==identity and state['proxy']==metadata)
        if state['stage']=='resolved':
            proof=json.loads(read(directory/'resolution-proof.json'))
            contract.require(contract.digest(proof)==state['proof_sha256'])
            contract.validate(proof,namespace,operation,state['payload']['request_id'],
                proxy_source=hashlib.sha256((ROOT/'model_proxy.py').read_bytes()).hexdigest())
            return proof
        contract.require(state['stage']=='resolution_intent' and (observe or finish))
        if finish:
            prior=json.loads(read(directory/'resolution-observation.json'))
            contract.require(prior['returncode']==0 and json.loads(prior['stdout']).get('stage')=='resolution_incomplete')
        payload=state['payload']
    else:
        contract.require(not observe and not finish and proxy.get('State',{}).get('Running') is True)
        found=effect(['docker','exec','-w','/',authority.identity,'python','-c',SOURCE,source,previous],timeout=30)
        contract.require(found.returncode==0 and len(found.stdout)<=4096)
        request=json.loads(found.stdout)['request_id'];contract.canonical(request)
        logs=effect(['docker','logs','--timestamps',proxy['Id']],timeout=30)
        contract.require(logs.returncode==0)
        original=logs.stdout+'\n'+logs.stderr;upstream=event_from_logs(original,request)
        save(directory/'proxy-logs.json',dict(container_id=proxy['Id'],stdout=logs.stdout,stderr=logs.stderr))
        payload=dict(namespace=namespace,maintenance_operation=operation,request_id=request,
            proxy_container=proxy['Id'],proxy_image=proxy['Image'],event=upstream,operator_confirmed=True)
        state=dict(identity=identity,stage='resolution_intent',proxy=metadata,payload=payload,
            logs_sha256=contract.digest(dict(container_id=proxy['Id'],stdout=logs.stdout,stderr=logs.stderr)))
        save(statefile,state)
    contract.require(proxy.get('State',{}).get('Running') is True)
    # A previous uncertain reply only permits an observation of its saved
    # receipt, not another official request or pause mutation.
    program=contract.program('finish' if finish else 'observe' if observe else 'resolve')
    try:
        result=effect(['docker','exec','-i','-w','/',proxy['Id'],'python','-c',program],input=json.dumps(payload))
    except subprocess.TimeoutExpired:
        return dict(stage='observation_required',model_calls=0,delivery_approval=False)
    save(directory/('resolution-finish.json' if finish else 'resolution-observation.json' if observe else 'resolution-output.json'),
        dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    contract.require(result.returncode==0 and len(result.stdout.encode())<=16384)
    proof=json.loads(result.stdout)
    if proof.get('stage') in ('not_observed','in_progress','resolution_incomplete'):return proof
    contract.validate(proof,namespace,operation,payload['request_id'],
        proxy_source=hashlib.sha256((ROOT/'model_proxy.py').read_bytes()).hexdigest())
    contract.require(same_proxy(namespace,inspect(proxy['Id']))==metadata
        and authority.inspect_controller()==authority.identity)
    save(directory/'resolution-proof.json',proof)
    state.update(stage='resolved',proof_sha256=contract.digest(proof));save(statefile,state)
    return proof


def register(namespace,image,source,previous,operation,qualification_id,*,payment_qualification=None,confirmed=False,observe=False):
    contract.require(confirmed is True)
    for value in (source,previous,operation,qualification_id):contract.canonical(value)
    contract.canonical(payment_qualification)
    authority=Authority(namespace,image);authority.inspect_controller()
    directory=archive(namespace,operation);statefile=directory/'registration-state.json'
    identity=dict(namespace=namespace,image=image,source=source,previous=previous,operation=operation,
        qualification_id=qualification_id,payment_qualification=payment_qualification)
    if statefile.exists():
        state=json.loads(read(statefile));contract.require(state['identity']==identity)
        if state['stage']=='registered':return state['receipt']
        contract.require(state['stage']=='registration_intent' and observe)
        payload=state['payload']
    else:
        contract.require(not observe)
        held,_=require_idle(namespace);contract.require(held['operation_id']==operation)
        runtime=payment_runtime(namespace,image,payment_qualification,observe=True)
        contract.require(runtime.get('operation')=='qualified_fixed_payment_runtime_v1'
            and runtime['namespace']==namespace and runtime['image']==image and runtime['maintenance_operation']==operation
            and runtime['qualification_id']==payment_qualification and runtime['container_retired'] is True
            and type(runtime['model_calls']) is int and runtime['model_calls']==0
            and type(runtime['real_provider_calls']) is int and runtime['real_provider_calls']==0
            and runtime['delivery_approval'] is False)
        proof=json.loads(read(directory/'resolution-proof.json'))
        resolved=json.loads(read(directory/'resolution-state.json'))
        logs=json.loads(read(directory/'proxy-logs.json'))
        contract.require(resolved['stage']=='resolved' and resolved['proof_sha256']==contract.digest(proof)
            and resolved['identity']==dict(namespace=namespace,image=image,source=source,previous=previous,
                operation=operation,resolver_sha256=contract.source_sha256())
            and contract.digest(logs)==resolved['logs_sha256'] and logs['container_id']==proof['proxy_container']
            and event_from_logs(logs['stdout']+'\n'+logs['stderr'],proof['request_id'])==proof['event'])
        contract.validate(proof,namespace,operation,proof['request_id'],
            proxy_source=hashlib.sha256((ROOT/'model_proxy.py').read_bytes()).hexdigest())
        proxy=inspect(namespace+'-model-proxy-1')
        contract.require(proxy.get('State',{}).get('Running') is False and same_proxy(namespace,proxy)==resolved['proxy'])
        payload=dict(source_task=source,previous_task=previous,maintenance_operation=operation,
            qualification=qualification(namespace,qualification_id,operation),provider_resolution=proof,
            runtime_identity=dict(image=image,container_id=authority.identity))
        state=dict(identity=identity,stage='registration_intent',payload=payload);save(statefile,state)
    try:
        result=effect(['docker','exec','-i','-w','/',authority.identity,'python','-c',REGISTER,
            'observe' if observe else 'register'],input=json.dumps(payload),timeout=120)
    except subprocess.TimeoutExpired:return dict(stage='observation_required',model_calls=0,delivery_approval=False)
    contract.require(result.returncode==0 and len(result.stdout.encode())<=16384
        and authority.inspect_controller()==authority.identity)
    receipt=json.loads(result.stdout)
    contract.require(receipt['model_calls']==0 and receipt['delivery_approval'] is False
        and receipt['tests_approved'] is False and receipt['incident_closed'] is False)
    if receipt['stage']=='registered':state.update(stage='registered',receipt=receipt);save(statefile,state)
    else:contract.require(observe and receipt['stage']=='not_observed')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','source','previous-task','operation'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--action',choices=('resolve','observe-resolution','finish-resolution','register','observe-registration'),required=True)
    parser.add_argument('--qualification')
    parser.add_argument('--payment-qualification')
    parser.add_argument('--operator-confirms-remediation',action='store_true')
    args=parser.parse_args();options=dict(confirmed=args.operator_confirms_remediation,observe=args.action.startswith('observe-'))
    if args.action.endswith('resolution') or args.action=='resolve':
        result=resolve(args.namespace,args.image,args.source,args.previous_task,args.operation,
            finish=args.action=='finish-resolution',**options)
    else:result=register(args.namespace,args.image,args.source,args.previous_task,args.operation,args.qualification,
        payment_qualification=args.payment_qualification,**options)
    print(json.dumps({k:result[k] for k in ('stage','operation','model_calls','delivery_approval','tests_approved','incident_closed') if k in result},sort_keys=True))
