"""Fixed local Compose deployment and HTTP QA. No worker-supplied commands.

Runs only integrated, CI-proven source, in a credential-free internal network.
The receipt is a local environment result, never release homologation.
"""
import hashlib,json,re,subprocess,time,urllib.parse
from pathlib import Path
from product_workspace import digest,validate_files

ADAPTER_VERSION='local-deploy-20260921-v2'
def immutable_file(path,text):
    if path.exists():
        if path.read_text()!=text:raise PermissionError('immutable deployment artifact drift: '+path.name)
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text);path.chmod(0o444)
PROXY="""import net from 'node:net';
const target=process.env.APP_SERVICE;
net.createServer(client=>{
 const upstream=net.connect(8080,target);
 client.setTimeout(15000,()=>client.destroy());upstream.setTimeout(15000,()=>upstream.destroy());
 client.on('error',()=>upstream.destroy());upstream.on('error',()=>client.destroy());
 client.on('close',()=>upstream.destroy());upstream.on('close',()=>client.destroy());
 client.pipe(upstream);upstream.pipe(client);
}).listen(8080,'0.0.0.0');
"""

def validate(spec,packet):
    if not isinstance(spec,dict) or set(spec)!={'entry','health_path','checks','reason'}:raise ValueError('exact local deployment specification required')
    if not re.fullmatch(r'dist/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:js|mjs)',spec['entry']):raise PermissionError('compiled dist entry required')
    if not isinstance(spec['reason'],str) or not 100<=len(spec['reason'])<=8000:raise ValueError('deployment rationale required')
    def path(value):
        if not isinstance(value,str) or not value.startswith('/') or value.startswith('//') or len(value)>300 or any(ord(c)<32 for c in value) or urllib.parse.urlsplit(value).netloc:raise PermissionError('relative local HTTP path required')
    path(spec['health_path'])
    if not isinstance(spec['checks'],list) or not 1<=len(spec['checks'])<=20:raise ValueError('bounded nonempty acceptance checks required')
    for check in spec['checks']:
        if not isinstance(check,dict) or set(check)!={'path','status','contains'}:raise ValueError('fixed HTTP check fields required')
        path(check['path'])
        if type(check['status'])!=int or not 100<=check['status']<=599 or not isinstance(check['contains'],str) or len(check['contains'])>1000:raise ValueError('bounded expected HTTP result required')
    if not re.fullmatch(r'[0-9a-f]{40}',packet.get('head','')) or packet.get('integration',{}).get('state')!='INTEGRATED' or packet['integration'].get('merge')!=packet['head']:raise PermissionError('exact integrated commit required')
    if packet.get('ci',{}).get('conclusion')!='success':raise PermissionError('actual successful integrated-source CI required')
    validate_files(packet['files'])

STARTER="""import {spawn,spawnSync} from 'node:child_process';
const checked=spawnSync(process.execPath,['/opt/toolchain/run.mjs'],{stdio:'inherit'});
if(checked.status!==0)process.exit(2);
const child=spawn(process.execPath,[process.env.APP_ENTRY],{cwd:'/tmp/work',stdio:'inherit',env:{PATH:process.env.PATH,HOME:'/tmp',NODE_ENV:'production',PORT:'8080',HOST:'0.0.0.0',APP_COMMIT:process.env.APP_COMMIT}});
for(const sig of ['SIGTERM','SIGINT'])process.on(sig,()=>child.kill(sig));
child.on('exit',code=>process.exit(code??1));
"""

def compose(folder,image,identity,head,entry,health):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image) or not re.fullmatch(r'[0-9a-f]{16}',identity):raise PermissionError('pinned scoped deployment identity required')
    name='homologation-'+identity
    service=dict(image=image,container_name='truco-online-'+name,user='10000:10000',read_only=True,cap_drop=['ALL'],security_opt=['no-new-privileges:true'],pids_limit=128,mem_limit='1g',cpus=1,
        entrypoint=['node','/operation/start.mjs'],environment=dict(APP_ENTRY=entry,APP_COMMIT=head),
        volumes=[dict(type='bind',source=str(folder/'source'),target='/workspace',read_only=True),dict(type='bind',source=str(folder/'operation'),target='/operation',read_only=True)],
        tmpfs=['/tmp:rw,nosuid,noexec,size=256m'],networks=[name],
        labels={'com.codifydeep.project':'truco-online','com.codifydeep.environment':'homologation','com.codifydeep.delivery':identity,'com.codifydeep.commit':head},
        healthcheck=dict(test=['CMD','node','-e','fetch("http://127.0.0.1:8080"+'+json.dumps(health)+').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))'],interval='5s',timeout='3s',retries=24,start_period='10s'))
    ingress=name+'-ingress'
    proxy=dict(image=image,container_name='truco-online-'+ingress,user='10000:10000',read_only=True,
        cap_drop=['ALL'],security_opt=['no-new-privileges:true'],pids_limit=32,mem_limit='128m',cpus=0.25,
        entrypoint=['node','/ingress/proxy.mjs'],environment=dict(APP_SERVICE=name),
        volumes=[dict(type='bind',source=str(folder/'ingress'),target='/ingress',read_only=True)],
        ports=['127.0.0.1::8080'],networks=[name,ingress],labels=dict(service['labels']))
    return dict(name='truco-online',services={name:service,ingress:proxy},networks={name:dict(internal=True),ingress:dict(internal=False)})

def command(args,timeout=150):
    r=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=timeout)
    if r.returncode:raise RuntimeError('local environment command failed: '+r.stderr[-3000:])
    return r.stdout

def _run(root,packet,proposal):
    spec=proposal['specification'];validate(spec,packet);identity=digest(proposal)[:16]
    folder=Path(root)/('environment-'+identity);folder.mkdir(exist_ok=True,mode=0o755)
    (folder/'source').mkdir(exist_ok=True);(folder/'operation').mkdir(exist_ok=True)
    expected=dict(packet['files']);expected_operation={'start.mjs':STARTER}
    for target,files in ((folder/'source',expected),(folder/'operation',expected_operation)):
        existing={p.relative_to(target).as_posix():p.read_text() for p in target.rglob('*') if p.is_file()}
        if existing and existing!=files:raise PermissionError('immutable deployment artifact drift')
        for name,text in files.items():
            immutable_file(target/name,text)
    definition=compose(folder,packet['validation_image'],identity,packet['head'],spec['entry'],spec['health_path'])
    ingress=folder/'ingress';ingress.mkdir(exist_ok=True)
    proxy_file=ingress/'proxy.mjs'
    if proxy_file.exists() and proxy_file.read_text()!=PROXY:raise PermissionError('fixed ingress drift')
    immutable_file(proxy_file,PROXY)
    path=folder/'compose-v2.json';raw=json.dumps(definition,sort_keys=True)
    if path.exists() and path.read_text()!=raw:raise PermissionError('compose drift')
    immutable_file(path,raw)
    service='homologation-'+identity;name='truco-online-'+service
    existing=command(['ps','-aq','--filter','name=^/'+name+'$']).strip()
    if existing:
        current=json.loads(command(['inspect',name]))[0]
        if current['Config']['Labels'].get('com.codifydeep.delivery')!=identity or current['Image']!=packet['validation_image']:raise PermissionError('foreign existing environment; never replace it')
    command(['compose','-p','truco-online','-f',str(path),'up','-d','--no-deps','--pull','never',service,service+'-ingress'])
    for _ in range(100):
        info=json.loads(command(['inspect',name]))[0]
        if info['Config']['Labels'].get('com.codifydeep.delivery')!=identity or info['Image']!=packet['validation_image']:raise PermissionError('foreign environment identity')
        if info['State'].get('Health',{}).get('Status')=='healthy':break
        if not info['State']['Running']:raise RuntimeError('integrated application failed startup: '+command(['logs','--tail','30',name])[-4000:])
        time.sleep(1)
    else:raise TimeoutError('local deployment health timeout')
    # Fixed probe has no shell or arbitrary URL, runs inside the isolated local app network.
    checks=json.dumps(spec['checks'])
    probe='const checks='+checks+'; for(const c of checks){const r=await fetch("http://127.0.0.1:8080"+c.path,{redirect:"error",signal:AbortSignal.timeout(3000)});const b=await r.text();if(b.length>1048576||r.status!==c.status||!b.includes(c.contains))throw Error("HTTP assertion failed: "+c.path);} console.log("HTTP_CHECKS_PASSED "+checks.length);'
    output=command(['exec',name,'node','--input-type=module','-e',probe],timeout=75)
    # First-deploy rollback is removal from service and restoration of the same immutable artifact.
    command(['stop','-t','5',name]);stopped=json.loads(command(['inspect',name]))[0]
    if stopped['State']['Running']:raise PermissionError('undeploy failed')
    command(['start',name]);
    for _ in range(100):
        info=json.loads(command(['inspect',name]))[0]
        if info['State'].get('Health',{}).get('Status')=='healthy':break
        time.sleep(1)
    else:raise TimeoutError('restore health timeout')
    output+=command(['exec',name,'node','--input-type=module','-e',probe],timeout=75)
    output+=command(['exec',name+'-ingress','node','--input-type=module','-e',probe],timeout=75)
    proxy_info=json.loads(command(['inspect',name+'-ingress']))[0]
    bindings=proxy_info['NetworkSettings']['Ports'].get('8080/tcp') or []
    if len(bindings)!=1 or bindings[0].get('HostIp')!='127.0.0.1' or not bindings[0].get('HostPort','').isdigit():raise PermissionError('loopback port not published')
    port=bindings[0]['HostPort']
    return dict(passed=True,commit=packet['head'],image=packet['validation_image'],source_sha256=digest(packet['files']),proposal_sha256=digest(proposal),container=name,url='http://127.0.0.1:'+port,
        checks=len(spec['checks']),log_sha256=hashlib.sha256(output.encode()).hexdigest(),healthy=True,undeploy_restore_verified=True,previous_version_rollback_verified=False,release_homologated=False,adapter_version=ADAPTER_VERSION,host_access_verified=False)

def run(root,packet,proposal):
    try:return _run(root,packet,proposal)
    except Exception as exc:
        identity=digest(proposal)[:16];name='truco-online-homologation-'+identity
        detail=''
        try:
            current=json.loads(command(['inspect',name]))[0]
            if current['Config']['Labels'].get('com.codifydeep.delivery')==identity and current['Config']['Labels'].get('com.codifydeep.commit')==packet['head']:
                detail=command(['logs','--tail','60',name])[-8000:]
                (Path(root)/('environment-'+identity)/'failure.log').write_text(detail)
                if current['State']['Running']:command(['stop','-t','5',name])
        except Exception:pass # Preserve the primary failure; never touch unknown resources.
        raise RuntimeError(type(exc).__name__+': '+str(exc)+'\nPreserved environment log: '+detail[-3000:]) from exc
