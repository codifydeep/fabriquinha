"""Sealed, backed-up installation of v2 source with all execution flags OFF.

Only recreates the owned execution-broker; never changes other services, mounts,
worker/model configuration, maintenance ownership or a delivery gate. An unknown
Compose acknowledgement is observed from the original intent, never replayed.
Private recovery material must never be published.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from qualify_quality_red_observer import require_idle
from quality_candidate_authority import Authority,Pending

ROOT=Path(__file__).resolve().parent
FLAGS=('BROKER_QUALITY_V2_ENABLED','BROKER_QUALITY_REVIEW_ENABLED','BROKER_QUALITY_IMPLEMENTATION_ENABLED','BROKER_QUALITY_TEAM_ENABLED')


def require(value):
    if not value:raise ValueError('preview installation precondition rejected; preserve private recovery evidence')


def save(path,value):
    temporary=path.with_suffix('.tmp');require(not path.is_symlink() and not temporary.exists())
    with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as out:
        json.dump(value,out,sort_keys=True);out.flush();os.fsync(out.fileno())
    os.replace(temporary,path)
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def command(argv,*,env=None,timeout=45):
    return subprocess.run(argv,env=env,capture_output=True,text=True,timeout=timeout,check=True)


def inspect(name):
    rows=json.loads(command(['docker','container','inspect',name]).stdout);require(len(rows)==1);return rows[0]


def archive_controller_logs(before,private):
    path=private/'previous-controller-logs.json'
    if path.exists():
        value=json.loads(path.read_bytes());require(value['container_id']==before['Id']);return
    result=command(['docker','logs','--timestamps',before['Id']])
    require(len(result.stdout.encode())+len(result.stderr.encode())<=67108864)
    save(path,dict(container_id=before['Id'],stdout=result.stdout,stderr=result.stderr))


def environment():
    allowed={'PATH','HOME','TMPDIR','DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','XDG_RUNTIME_DIR'}
    return {k:v for k,v in os.environ.items() if k in allowed}


def disabled_sources(files,*,runtime=False):
    """Explicit OFF overlay must win even after a previous exclusive activation."""
    preview=ROOT/'compose.quality-v2-preview.yaml';values=[p for p in files if p!=preview]
    selectors=ROOT/'compose.quality-v2-runtime.yaml'
    if runtime and selectors not in values:values.append(selectors)
    return [*values,preview]


def configuration(before,namespace):
    labels=before.get('Config',{}).get('Labels',{})
    require(labels.get('com.docker.compose.project')==namespace and labels.get('com.docker.compose.service')=='execution-broker'
        and before.get('Name')=='/'+namespace+'-execution-broker-1' and before.get('State',{}).get('Running') is True)
    files=[Path(p) for p in labels['com.docker.compose.project.config_files'].split(',')]
    envfiles=[Path(p) for p in labels['com.docker.compose.project.environment_file'].split(',')]
    for path in files+envfiles:
        require(path.is_absolute() and path.is_file() and path.resolve()==path and path.is_relative_to(ROOT))
    require(all(not p.stat().st_mode&0o077 for p in envfiles)
        and Path(labels['com.docker.compose.project.working_dir'])==ROOT)
    argv=['docker','compose','--project-name',namespace,'--project-directory',str(ROOT)]
    for path in envfiles:argv+=['--env-file',str(path)]
    return argv,files


def interpolation(before,namespace,companions):
    """Recover non-secret startup variables that were previously shell-only."""
    old=dict(v.split('=',1) for v in before['Config'].get('Env',[]))
    worker=old.get('BROKER_WORKER_IMAGE','');require(re.fullmatch('sha256:[a-f0-9]{64}',worker))
    values=dict(BROKER_WORKER_IMAGE=worker,DELIVERY_KIT_COMPOSE_PROJECT=namespace)
    for service,port,key in (('backend','8080/tcp','EVAL_BACKEND_PORT'),('frontend','3000/tcp','EVAL_FRONTEND_PORT')):
        row=companions[service];labels=row['Config']['Labels']
        require(labels.get('com.docker.compose.project')==namespace and labels.get('com.docker.compose.service')==service)
        bindings=row['HostConfig']['PortBindings'][port]
        require(len(bindings)==1 and bindings[0]['HostIp']=='127.0.0.1' and bindings[0]['HostPort'].isdigit())
        values[key]=bindings[0]['HostPort']
    proxy=companions['model-proxy'];labels=proxy['Config']['Labels']
    require(labels.get('com.docker.compose.project')==namespace and labels.get('com.docker.compose.service')=='model-proxy')
    count=dict(v.split('=',1) for v in proxy['Config'].get('Env',[])).get('MODEL_PROXY_MAX_CALLS','')
    require(count.isdigit() and int(count)>0);values['MODEL_PROXY_MAX_CALLS']=count
    return values


def verify_preservation(before,after,image,*,socket_daemon_verified=False,runtime=None):
    from quality_runtime_configuration import syntax
    runtime=syntax(runtime) if runtime is not None else {}
    require(after['Image']==image and after['State']['Running'] is True)
    old_mounts=json.loads(json.dumps(before['Mounts']));new_mounts=json.loads(json.dumps(after['Mounts']))
    socket_sources={'/run/host-services/docker.proxy.sock','/var/run/docker.sock'}
    origin_changed=False
    old_socket=next((m for m in old_mounts if m['Destination']=='/var/run/docker.sock'),None)
    new_socket=next((m for m in new_mounts if m['Destination']=='/var/run/docker.sock'),None)
    if old_socket and new_socket and old_socket.get('Source')!=new_socket.get('Source'):
        require(socket_daemon_verified and {old_socket.get('Source'),new_socket.get('Source')}==socket_sources)
        require(all(m.get('Type')=='bind' and m.get('RW') is True and m.get('Mode')=='rw' for m in (old_socket,new_socket)))
        old_socket['Source']=new_socket['Source']='/var/run/docker.sock';origin_changed=True
    for key in ('Mounts',):
        normalize=lambda value:sorted(value,key=lambda item:item['Destination'])
        require(normalize(old_mounts)==normalize(new_mounts))
    for key in ('User','Entrypoint','Cmd','WorkingDir'):
        require(before['Config'].get(key)==after['Config'].get(key))
    for key in ('ReadonlyRootfs','CapDrop','SecurityOpt','Memory','NanoCpus','PidsLimit','Privileged','PortBindings','NetworkMode','Tmpfs'):
        require(before['HostConfig'].get(key)==after['HostConfig'].get(key))
    def binds(value):
        rows=list(value['HostConfig'].get('Binds') or [])
        if origin_changed:rows=[r.replace('/run/host-services/docker.proxy.sock:/var/run/docker.sock:',
            '/var/run/docker.sock:/var/run/docker.sock:') for r in rows]
        return sorted(rows)
    require(binds(before)==binds(after))
    old=dict(v.split('=',1) for v in before['Config'].get('Env',[]));new=dict(v.split('=',1) for v in after['Config'].get('Env',[]))
    require(all(new.get(k)==v for k,v in old.items() if k not in FLAGS and k not in runtime)
        and all(new.get(k)==v for k,v in runtime.items()) and all(new.get(k)=='0' for k in FLAGS)
        and set(new)<=set(old)|set(FLAGS)|set(runtime))
    return origin_changed


def install(namespace,image,operation,*,runtime=None):
    from quality_runtime_configuration import syntax,probe
    if runtime is not None:runtime=syntax(runtime)
    require(re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace) and re.fullmatch('sha256:[a-f0-9]{64}',image)
        and str(uuid.UUID(operation))==operation)
    private=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-preview-install-'+operation)
    require(private.parent.resolve()==private.parent)
    private.mkdir(mode=0o700,exist_ok=True);require(private.resolve()==private and not private.stat().st_mode&0o077)
    statefile=private/'state.json';name=namespace+'-execution-broker-1';env=environment()
    if statefile.exists():
        state=json.loads(statefile.read_bytes());require(state['namespace']==namespace and state['image']==image
            and state['operation']==operation and state.get('runtime')==runtime)
        if state['stage']=='installed_disabled':return state['receipt']
        require(state['stage'] in ('planned','backed_up','recreate_intent'))
        before=json.loads((private/'before.json').read_bytes())
    else:
        maintenance,idle=require_idle(namespace);before=inspect(name)
        if runtime is not None:require(probe(namespace,before['Image'],runtime)==runtime)
        info=json.loads(command(['docker','image','inspect',image]).stdout)[0]
        require(info['Id']==image and info['Config']['Labels'].get('delivery-kit.component')=='quality-v2-controller')
        argv,files=configuration(before,namespace)
        # Pin persists in a private env file so a future Compose invocation does
        # not need a transient shell variable. Existing secret files are untouched.
        configdir=private.parent.parent/'controller-config';require(configdir.parent.resolve()==configdir.parent)
        configdir.mkdir(mode=0o700,exist_ok=True)
        require(configdir.resolve()==configdir and not configdir.stat().st_mode&0o077)
        pin=configdir/('quality-preview-'+operation+'.env')
        values=interpolation(before,namespace,{s:inspect(namespace+'-'+s+'-1') for s in ('backend','frontend','model-proxy')})
        values['DELIVERY_KIT_QUALITY_V2_CONTROLLER_IMAGE']=image
        if runtime is not None:values.update(runtime)
        content=''.join(k+'='+v+'\n' for k,v in sorted(values.items()))
        if pin.exists():
            require(not pin.is_symlink() and not pin.stat().st_mode&0o077)
            old=dict(line.split('=',1) for line in pin.read_text().splitlines())
            require(set(old)<=set(values) and all(values[k]==v for k,v in old.items()))
        if not pin.exists() or pin.read_text()!=content:
            temporary=pin.with_suffix('.tmp');require(not temporary.exists())
            with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as out:
                out.write(content);out.flush();os.fsync(out.fileno())
            os.replace(temporary,pin)
            descriptor=os.open(configdir,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        argv+=['--env-file',str(pin)]
        for path in disabled_sources(files,runtime=runtime is not None):argv+=['-f',str(path)]
        save(private/'before.json',before)
        resolved=json.loads(command([*argv,'config','--format','json'],env=env).stdout)
        require(resolved['services']['execution-broker']['image']==image)
        old=dict(v.split('=',1) for v in before['Config'].get('Env',[]))
        target=resolved['services']['execution-broker']['environment']
        explicit=runtime or {}
        require(all(target.get(k)=='0' for k in FLAGS)
            and all(target.get(k)==v for k,v in explicit.items())
            and all(k in FLAGS or k in explicit or old.get(k)==v for k,v in target.items()))
        save(private/'resolved-private.json',resolved)
        others=[json.loads(line) for line in command(['docker','ps','-a','--no-trunc','--format','json']).stdout.splitlines() if line]
        save(private/'other-containers.json',[dict(id=c['ID'],names=c['Names'],status=c['State']) for c in others if c['Names']!=name])
        state=dict(namespace=namespace,image=image,operation=operation,stage='planned',deadline=time.time()+900,
            maintenance_operation=maintenance['operation_id'],argv=argv,previous_id=before['Id'])
        if runtime is not None:state['runtime']=runtime
        save(statefile,state)
    if state['stage']=='planned':
        maintenance,_=require_idle(namespace)
        require(maintenance['operation_id']==state['maintenance_operation'] and inspect(name)['Id']==state['previous_id'])
        backup=command([sys.executable,str(ROOT/'scripts/backup_sealed_controller.py'),'--namespace',namespace,
            '--operation',state['maintenance_operation'],'--compressed','--backup-id',operation,'--max-archive-mib','128'],timeout=55)
        receipt=json.loads(backup.stdout);save(private/'backup-receipt.json',receipt)
        if receipt.get('restore_integrity')!='ok':raise Pending('observe original backup and receipt; no controller replacement yet')
        require(receipt['backup_id']==operation and receipt['operation_id']==state['maintenance_operation'])
        archive=private/'leases.sqlite.gz'
        if not archive.exists():
            save(private/'backup-copy-intent.json',dict(source=receipt['path'],target=str(archive)))
            command(['docker','cp',before['Id']+':'+receipt['path'],str(archive)],timeout=45);archive.chmod(0o600)
        with archive.open('rb') as stream:require(hashlib.file_digest(stream,'sha256').hexdigest()==receipt['archive_sha256'])
        native=private/'native.json'
        if not native.exists():command(['docker','cp',before['Id']+':/broker-state/native.json',str(native)]);native.chmod(0o600)
        state['stage']='backed_up';save(statefile,state)
    if state['stage']=='backed_up':
        require(inspect(name)['Id']==state['previous_id']);maintenance,_=require_idle(namespace)
        require(maintenance['operation_id']==state['maintenance_operation'])
        archive_controller_logs(before,private)
        state['stage']='recreate_intent';save(statefile,state)
        try:command([*state['argv'],'up','-d','--no-deps','--pull','never','execution-broker'],env=env,timeout=45)
        except (subprocess.SubprocessError,OSError):pass  # Observe the original intent, never another up.
    after=inspect(name)
    if after['Id']==before['Id'] or after['Image']!=image or after['State'].get('Running') is not True:
        if time.time()>=state['deadline']:
            state.update(stage='technical_blocked',next_action='DevOps inspect original Compose effect; no repeated up or automatic rollback')
            save(statefile,state);raise ValueError('preview replacement observation deadline; evidence preserved')
        raise Pending('observe original Compose replacement; never repeat its up command')
    # Docker Desktop may resolve its historical proxy socket to the native
    # socket after an upgrade. This is the sole allowed source alias, and only
    # with the same daemon verified from inside this exact controller. Other
    # binds, destinations, access modes, resources and data volumes stay exact.
    host_daemon=command(['docker','info','--format','{{.ID}}']).stdout.strip()
    inside=command(['docker','exec',after['Id'],'python','-c',
        'import sys;sys.path.insert(0,"/");import broker as b;print(b.docker("GET","/info")["ID"])']).stdout.strip()
    require(bool(host_daemon) and host_daemon==inside)
    origin_changed=verify_preservation(before,after,image,socket_daemon_verified=True,runtime=runtime)
    about=Authority(namespace,image).about()
    require(about['maintenance'] is True and about['v2_enabled'] is False and about['implementation_enabled'] is False)
    maintenance,idle=require_idle(namespace);require(maintenance['operation_id']==state['maintenance_operation'])
    previous=json.loads((private/'other-containers.json').read_bytes())
    for row in previous:
        actual=inspect(row['id']);require(actual['Name']=='/'+row['names'] and actual['State']['Status']==row['status'])
    receipt=dict(operation='quality_preview_install_v2',stage='installed_disabled',namespace=namespace,image=image,
        previous_image=before['Image'],container_id=after['Id'],maintenance_sealed=True,native_active=0,active_leases=0,
        data_mounts_preserved=True,docker_socket_daemon_verified=True,docker_socket_origin_alias_changed=origin_changed,
        other_containers_unchanged=True,model_calls=0,delivery_approval=False)
    if runtime is not None:receipt['runtime_configured_execution_disabled']=True
    state.update(stage='installed_disabled',receipt=receipt);save(statefile,state);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--namespace',required=True);p.add_argument('--image',required=True)
    p.add_argument('--operation',required=True)
    p.add_argument('--runtime-config',help='Private exact image/role selectors; all execution flags stay off')
    args=p.parse_args()
    from quality_runtime_configuration import load
    runtime=load(args.runtime_config) if args.runtime_config else None
    print(json.dumps(install(args.namespace,args.image,args.operation,runtime=runtime),sort_keys=True))
