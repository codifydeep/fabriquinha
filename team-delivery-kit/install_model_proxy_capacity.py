"""Sealed, qualified replacement of ONLY the stopped owned model proxy.

Archives source/logs/counter before recreation, keeps the exact meter/key/data
mounts and call ceiling, checks runtime via GET only, then leaves the new proxy
stopped. Unknown Compose/stop/copy effects are observed, never replayed. No
review recovery, model call, credential read, volume deletion or approval.
"""
import argparse
import ast
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import time
import uuid
import install_quality_preview as base
from migrate_quality_candidate_pin import read,folder
from qualify_quality_red_observer import require_idle
import qualify_model_proxy_capacity as qualification
from quality_git_candidate import require,Pending

ROOT=Path(__file__).resolve().parent


@contextmanager
def installation_lock(private):
    descriptor=os.open(private/'model-proxy-install.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077)
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Pending('the original proxy installation owns the kernel lock') from None
        yield
    finally:os.close(descriptor)


def private_digest(path):
    info=path.stat()
    require(path.resolve()==path and not path.is_symlink() and stat.S_ISREG(info.st_mode)
        and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077 and info.st_size<=67108864)
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def environment(info):
    rows=info['Config'].get('Env',[]);values=dict(v.split('=',1) for v in rows)
    require(len(rows)==len(values));return values


def counter_receipt(raw):
    require(isinstance(raw,bytes) and 0<len(raw)<=512)
    value=json.loads(raw)
    require(isinstance(value,dict) and set(value)=={'calls'} and type(value['calls']) is int and value['calls']>=0)
    return dict(calls=value['calls'],sha256=qualification.sha(raw))


def verify_proxy(before,after,image,*,running=True):
    require(type(running) is bool and after['Name']==before['Name'] and after['Image']==image
        and after['State']['Running'] is running)
    labels=before['Config']['Labels'];actual=after['Config']['Labels']
    require(labels.get('com.docker.compose.service')=='model-proxy'
        and all(actual.get(k)==labels.get(k) for k in ('com.docker.compose.project','com.docker.compose.service')))
    for key in ('User','Entrypoint','Cmd','WorkingDir'):require(before['Config'].get(key)==after['Config'].get(key))
    for key in ('ReadonlyRootfs','CapDrop','SecurityOpt','Memory','NanoCpus','PidsLimit','Privileged',
            'PortBindings','NetworkMode','Tmpfs'):
        require(before['HostConfig'].get(key)==after['HostConfig'].get(key))
    require(sorted(before['HostConfig'].get('Binds') or [])==sorted(after['HostConfig'].get('Binds') or [])
        and sorted(before['Mounts'],key=lambda m:m['Destination'])==sorted(after['Mounts'],key=lambda m:m['Destination'])
        and all(m['Destination']!='/var/run/docker.sock' for m in after['Mounts']))
    require(environment(after)=={**environment(before),'MODEL_PROXY_MAX_REQUEST_BYTES':'2097152'})


def qualified(namespace,identifier,operation,image):
    require(str(uuid.UUID(identifier))==identifier)
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('model-proxy-capacity-'+identifier)
    state=json.loads(read(archive/'state.json'));output=json.loads(read(archive/'output.json'));receipt=state['receipt']
    require(state['stage']=='qualified' and state['identity']['image']==image and output['returncode']==0
        and receipt['operation']=='qualified_model_proxy_capacity_v1' and receipt['qualification_id']==identifier
        and receipt['namespace']==namespace and receipt['proxy_image']==image and receipt['maintenance_operation']==operation
        and receipt['source_sha256']==qualification.sha((ROOT/'model_proxy.py').read_bytes())
        and receipt['script_sha256']==qualification.sha((ROOT/'tests/model_proxy_capacity_canary.py').read_bytes())
        and receipt['output_sha256']==qualification.sha(output['stdout'].encode())
        and receipt['container_retired'] is True and receipt['volumes_created']==0
        and receipt['model_calls']==0 and receipt['delivery_approval'] is False)
    qualification.validate_report(receipt['report'],receipt['source_sha256'])
    reports=[]
    for line in output['stdout'].splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if isinstance(value,dict) and value.get('operation')=='real_http_proxy_capacity_canary_v1':reports.append(value)
    require(reports==[receipt['report']]);return receipt


def copy_private(container,source,target):
    """Read the same copy after lost acknowledgment, never overwrite it."""
    if target.exists():return read(target)
    intent=target.with_name(target.name+'.copy-intent.json')
    if intent.exists():raise Pending('observe original private copy; no repeated docker cp')
    base.save(intent,dict(container_id=container,source=source,target=target.name))
    try:base.command(['docker','cp',container+':'+source,str(target)],timeout=20)
    except subprocess.SubprocessError:raise Pending('observe original private copy; do not overwrite') from None
    target.chmod(0o600);return read(target)


def old_capacity(program,values):
    """Qualify the original legacy 512 KiB constant, without executing source."""
    require('MODEL_PROXY_MAX_REQUEST_BYTES' not in values)
    nodes=[n.value for n in ast.parse(program).body if isinstance(n,ast.Assign)
        and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='MAX_BODY']
    require(len(nodes)==1)
    expected=ast.parse('512 * 1024',mode='eval').body
    require(ast.dump(nodes[0],include_attributes=False)==ast.dump(expected,include_attributes=False))
    return 524288


def install(namespace,image,operation,qualification_id):
    require(re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace)
        and re.fullmatch('sha256:[a-f0-9]{64}',image) and str(uuid.UUID(operation))==operation)
    private=folder(ROOT/('.local-'+namespace.removeprefix('delivery-kit-')))
    with installation_lock(private):return _install(namespace,image,operation,qualification_id)


def _install(namespace,image,operation,qualification_id):
    private=folder(folder(ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups')/('model-proxy-install-'+operation))
    statefile=private/'state.json';name=namespace+'-model-proxy-1'
    if statefile.exists():
        state=json.loads(read(statefile));require(state['namespace']==namespace and state['image']==image
            and state['operation']==operation and state['qualification_id']==qualification_id)
        if state['stage']=='installed_stopped':return state['receipt']
        require(state['stage'] in ('planned','recreate_intent','stop_intent'))
        before=json.loads(read(private/'before.json'))
    else:
        maintenance,_=require_idle(namespace);before=base.inspect(name)
        require(before['Name']=='/'+name and before['State']['Running'] is False and before['Image']!=image
            and before['Config']['Labels'].get('com.docker.compose.project')==namespace
            and before['Config']['Labels'].get('com.docker.compose.service')=='model-proxy')
        proof=qualified(namespace,qualification_id,maintenance['operation_id'],image)
        current=base.inspect(namespace+'-execution-broker-1');argv,files=base.configuration(current,namespace)
        values=base.interpolation(current,namespace,{s:base.inspect(namespace+'-'+s+'-1') for s in ('backend','frontend','model-proxy')})
        values['DELIVERY_KIT_MODEL_PROXY_IMAGE']=image
        pin=folder(private.parent.parent/'controller-config')/('model-proxy-capacity-'+operation+'.env')
        from quality_candidate_service import write_once
        write_once(pin,''.join(k+'='+v+'\n' for k,v in sorted(values.items())).encode())
        argv+=['--env-file',str(pin)]
        for path in files:argv+=['-f',str(path)]
        resolved=json.loads(base.command([*argv,'config','--format','json'],env=base.environment()).stdout)
        target=resolved['services']['model-proxy'];old=environment(before)
        require(target['image']==image and target['environment'].get('MODEL_PROXY_MAX_REQUEST_BYTES')=='2097152'
            and all(k=='MODEL_PROXY_MAX_REQUEST_BYTES' or old.get(k)==v for k,v in target['environment'].items())
            and old.get('MODEL_PROXY_COUNTER_PATH')=='/meter/calls.json' and old.get('MODEL_PROXY_MAX_CALLS','').isdigit())
        base.save(private/'before.json',before);base.save(private/'resolved-private.json',resolved)
        others=[json.loads(line) for line in base.command(['docker','ps','-a','--no-trunc','--format','json']).stdout.splitlines() if line]
        base.save(private/'other-containers.json',[dict(id=c['ID'],names=c['Names'],status=c['State']) for c in others if c['Names']!=name])
        state=dict(stage='planned',namespace=namespace,image=image,operation=operation,qualification_id=qualification_id,
            qualification=proof,maintenance_operation=maintenance['operation_id'],controller_id=current['Id'],
            argv=argv,deadline=time.time()+300,model_calls=0,delivery_approval=False)
        base.save(statefile,state)
    held,_=require_idle(namespace)
    require(held['operation_id']==state['maintenance_operation']
        and base.inspect(namespace+'-execution-broker-1')['Id']==state['controller_id'])
    if state['stage']=='planned':
        require(base.inspect(name)['Id']==before['Id'])
        counter=counter_receipt(copy_private(before['Id'],'/meter/calls.json',private/'counter-before.json'))
        source=copy_private(before['Id'],'/model_proxy.py',private/'previous-model_proxy.py')
        legacy=old_capacity(source,environment(before))
        logs=private/'previous-proxy-logs.json'
        if not logs.exists():
            observed=base.command(['docker','logs','--timestamps',before['Id']])
            require(len(observed.stdout.encode())+len(observed.stderr.encode())<=67108864)
            base.save(logs,dict(container_id=before['Id'],stdout=observed.stdout,stderr=observed.stderr))
        state.update(stage='recreate_intent',counter=counter,previous_capacity=legacy,
            previous_source_sha256=qualification.sha(source),previous_logs_sha256=private_digest(logs))
        base.save(statefile,state)
        try:base.command([*state['argv'],'up','-d','--no-deps','--pull','never','model-proxy'],env=base.environment(),timeout=45)
        except (subprocess.SubprocessError,OSError):pass  # Observe this intent, never repeat up.
    after=base.inspect(name)
    if after['Id']==before['Id'] or after['Image']!=image or state['stage']=='recreate_intent' and not after['State']['Running']:
        if time.time()>=state['deadline']:
            state['stage']='technical_blocked';base.save(statefile,state)
            raise ValueError('original proxy recreation not verified; preserve evidence, no repeated up')
        raise Pending('observe original proxy replacement; never repeat Compose up')
    if state['stage']=='recreate_intent':
        verify_proxy(before,after,image)
        program='''import json,urllib.request
print(json.dumps({p:json.load(urllib.request.urlopen("http://127.0.0.1:8080/"+p,timeout=5)) for p in ("status","runtime-status","provider-status")},sort_keys=True))'''
        try:runtime=json.loads(base.command(['docker','exec',after['Id'],'python','-c',program],timeout=20).stdout)
        except subprocess.SubprocessError:raise Pending('observe readiness of same proxy; never repeat recreation') from None
        require(runtime['runtime-status']['max_request_bytes']==2097152
            and runtime['status']['calls']==state['counter']['calls']
            and runtime['status']['max_calls']==int(environment(before)['MODEL_PROXY_MAX_CALLS'])
            and runtime['status']['remaining']==max(0,runtime['status']['max_calls']-runtime['status']['calls']))
        state.update(stage='stop_intent',runtime=runtime,new_container_id=after['Id']);base.save(statefile,state)
        try:base.command(['docker','stop','--time','5',after['Id']],timeout=20)
        except (subprocess.SubprocessError,OSError):pass
    after=base.inspect(name)
    require(after['Id']==state['new_container_id'])
    if after['State']['Running']:raise Pending('observe original proxy stop; never send another stop')
    verify_proxy(before,after,image,running=False)
    require(counter_receipt(copy_private(after['Id'],'/meter/calls.json',private/'counter-after.json'))==state['counter'])
    for row in json.loads(read(private/'other-containers.json')):
        actual=base.inspect(row['id']);require(actual['Name']=='/'+row['names'] and actual['State']['Status']==row['status'])
    held,_=require_idle(namespace);require(held['operation_id']==state['maintenance_operation'])
    receipt=dict(operation='model_proxy_capacity_install_v1',stage='installed_stopped',namespace=namespace,
        install_operation=operation,maintenance_operation=state['maintenance_operation'],qualification=state['qualification'],
        previous_container=before['Id'],current_container=after['Id'],previous_image=before['Image'],current_image=image,
        previous_capacity=state['previous_capacity'],max_request_bytes=2097152,source_sha256=state['qualification']['source_sha256'],
        previous_source_sha256=state['previous_source_sha256'],previous_logs_sha256=state['previous_logs_sha256'],
        counter=state['counter'],max_calls=state['runtime']['status']['max_calls'],
        data_mounts_preserved=True,credentials_mounts_preserved=True,other_containers_unchanged=True,
        maintenance_sealed=True,model_calls=0,delivery_approval=False)
    state.update(stage='installed_stopped',receipt=receipt);base.save(statefile,state);return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','operation','qualification'):parser.add_argument('--'+key,required=True)
    options=parser.parse_args()
    try:result=install(options.namespace,options.image,options.operation,options.qualification)
    except Pending:result=dict(stage='pending_observation',next_action='observe same installation; never replay effects',delivery_approval=False)
    print(json.dumps(result,sort_keys=True))
