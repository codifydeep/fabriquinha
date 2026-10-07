"""Offline controller/wrapper/Docker/Hermes startup canary.

Uses a disposable native identity fixture, not the installed Multica database.
Runs actual broker HTTP handlers, wrapper and ACP transport. One lost create
acknowledgement is injected *after* the real Docker operation. No prompt,
provider call, credential, product workspace or persistent volume is used.
"""
import argparse
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parent


def run(image,installed_controller=False,network_default=False):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('immutable probe image required')
    sys.path.insert(0,str(ROOT/'broker'))
    os.environ['BROKER_WORKER_IMAGE']=image
    controller_source=Path('/broker.py') if installed_controller else ROOT/'broker/server.py'
    spec=importlib.util.spec_from_file_location('startup_probe_broker',controller_source)
    b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
    import native
    import acp_startup
    task,agent,issue,request_id=[str(uuid.uuid4()) for _ in range(4)]
    capability=secrets.token_hex(32)
    settings=dict(workspace_id=str(uuid.uuid4()),agents={agent:'planning'})
    native_task=dict(id=task,agent_id=agent,issue_id=issue,status='running')
    current={'status':'running'}
    def native_record(value,task_id,agent_id):
        if value!=settings or task_id!=task or agent_id!=agent:raise ValueError('fixture identity drift')
        return {**native_task,**current}
    operations={'create':0,'start':0,'exec':0}
    real_docker=b.docker
    def delayed_docker(method,path,data=None):
        result=real_docker(method,path,data)
        if method=='POST' and path.startswith('/containers/create?'):
            operations['create']+=1
            time.sleep(2)
            raise b.DockerOperationTimeout(method,path)
        if method=='POST' and path.endswith('/start') and path.startswith('/containers/'):
            operations['start']+=1
        if method=='POST' and path.endswith('/exec'):operations['exec']+=1
        return result
    def fixed_config(actual_request,scenario):
        if actual_request!=request_id or scenario!='acp-session':raise ValueError('fixed startup probe only')
        return dict(Image=image,User='10000:10000',Entrypoint=['python'],
            Cmd=['-c','import time; time.sleep(480)'],WorkingDir='/tmp',NetworkDisabled=not network_default,
            Env=['HOME=/tmp','HERMES_HOME=/tmp/hermes'],
            Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.request':request_id,'com.docker.compose.project':b.PREFIX},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
                SecurityOpt=['no-new-privileges'],Memory=536870912,NanoCpus=1000000000,PidsLimit=96,
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=128m,mode=1777',
                    '/session-state':'rw,nosuid,nodev,size=64m,mode=700,uid=10000,gid=10000'},AutoRemove=False))
    observed=[]
    class Handler(b.Handler):
        def do_POST(self):
            started=time.monotonic();super().do_POST()
            observed.append((self.path,time.monotonic()-started))
        def log_message(self,*_):pass
    # Keep the private evidence even if Docker's deletion acknowledgement is
    # delayed. This is a small disposable fixture, never a product database.
    with nullcontext(tempfile.mkdtemp(prefix='delivery-kit-startup-integration-')) as directory:
        b.STATE=Path(directory);b.PREFIX='delivery-kit-port2';b.OWNER='delivery-kit-startup-probe-'+request_id
        b.TOKEN=secrets.token_hex(32);b.MODEL_NETWORK=''
        (b.STATE/'native.json').write_text(json.dumps(settings));(b.STATE/'native.json').chmod(0o600)
        with patch.object(native,'task_record',side_effect=native_record):
            binding=native.task_binding(settings,task,agent)
        with b.db() as con:
            con.execute('CREATE TABLE grants(digest TEXT PRIMARY KEY,task_id TEXT,attempt INTEGER,mode TEXT,request_id TEXT,deadline REAL,used INTEGER)')
            con.execute('CREATE TABLE native_bindings(request_id TEXT PRIMARY KEY,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
            con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
            con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            con.execute('CREATE TABLE issue_editables(issue_id TEXT,path TEXT)')
            con.execute('CREATE TABLE issue_test_commands(issue_id TEXT,command TEXT)')
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            con.execute('CREATE TABLE acp_sessions(scope TEXT,session_id TEXT)')
            con.execute('CREATE TABLE acp_events(request_id TEXT,method TEXT,session_id TEXT,success INTEGER)')
            con.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?)',(hashlib.sha256(capability.encode()).hexdigest(),task,1,'planning',request_id,time.time()+480,0))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',(request_id,task,agent,binding['scope'],issue))
        b.verify_worker_image()
        server=b.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        result=None
        with patch.object(native,'task_record',side_effect=native_record),patch.object(b,'config',side_effect=fixed_config),patch.object(b,'docker',side_effect=delayed_docker):
            try:
                environment={k:v for k,v in os.environ.items() if not any(s in k for s in ('API_KEY','TOKEN','PASSWORD','SECRET'))}
                environment['DELIVERY_EXECUTION_CAPABILITY']=capability
                code='import acp_wrapper;acp_wrapper.URL='+repr('http://127.0.0.1:'+str(server.server_port))+';acp_wrapper.main()'
                frame=dict(jsonrpc='2.0',id='real-initialize',method='initialize',params=dict(protocolVersion=1,clientCapabilities={}))
                output=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=environment,
                    input=json.dumps(frame)+'\n',capture_output=True,text=True,timeout=110)
                if output.returncode:raise RuntimeError('integrated wrapper startup failed')
                messages=[json.loads(line) for line in output.stdout.splitlines() if line.strip()]
                reply=next((m for m in messages if m.get('id')=='real-initialize'),{})
                if reply.get('result',{}).get('protocolVersion')!=1:raise ValueError('actual ACP initialize not received')
                with b.db() as con:
                    used=con.execute('SELECT used FROM grants').fetchone()[0]
                    status=con.execute('SELECT status FROM leases').fetchone()[0]
                    events=[tuple(row) for row in con.execute('SELECT method,success FROM acp_events')]
                if used!=1 or status not in ('closed','closing') or events!=[('initialize',1)] or operations!={'create':1,'start':1,'exec':1}:
                    raise ValueError('single-use startup or actual transport invariant failed')
                if not any(path=='/v1/acp-ready' for path,_ in observed):raise ValueError('pending startup not observed')
                first=[duration for path,duration in observed if path=='/v1/acp-startup']
                if len(first)!=1 or first[0]>=1:raise ValueError('startup HTTP did not return promptly')
                result=dict(schema='async-startup-integration-probe-v1',status='passed',
                    installed_controller_code=installed_controller,
                    controller_sha256=hashlib.sha256(controller_source.read_bytes()).hexdigest(),
                    worker_image=image,native_identity='disposable_fixture_not_real_multica',
                    actual_broker_http=True,actual_wrapper=True,actual_docker=True,actual_acp_transport=True,
                    actual_hermes_initialize=True,lost_create_ack_observed=True,
                    capability_consumptions=used,operations=operations,lease_status=status,
                    prompts_sent=0,sessions_created=0,model_calls=0,worker_network='none',
                    worker_socket_absent=True,delivery_approval=False)
                result['network_default_policy']=network_default
                receipt=b.STATE/'probe-receipt.json'
                receipt.write_text(json.dumps(result,sort_keys=True));receipt.chmod(0o600)
            finally:
                current['status']='cancelled'
                worker=acp_startup.THREADS.get(request_id)
                if worker:worker.join(timeout=35)
                server.shutdown();server.server_close();thread.join(timeout=3)
                if worker and worker.is_alive():raise RuntimeError('startup outcome still unknown; preserve exact probe')
                # A closed/closing lease already attempted deletion. Observe
                # its outcome rather than issuing a second DELETE blindly.
                with b.db() as con:
                    lease=con.execute('SELECT status FROM leases WHERE request_id=?',(request_id,)).fetchone()
                name=b.PREFIX+'-job-'+request_id
                if not lease or lease[0] not in ('closed','closing','failed'):
                    try:b.remove_owned(name,request_id)
                    except (b.DockerOperationTimeout,RuntimeError):pass  # observe same exact name below
                deadline=time.monotonic()+30;absent=False
                while time.monotonic()<deadline:
                    try:info=real_docker('GET','/containers/'+name+'/json')
                    except b.DockerOperationTimeout:
                        time.sleep(0.25);continue
                    if info is None:absent=True;break
                    time.sleep(0.25)
                if not absent:raise RuntimeError('probe retirement still pending; private evidence preserved')
                if result:
                    # Reconcile only after GET proved absence. The existing
                    # close operation sees no object and cannot repost DELETE.
                    b.session_operation(capability,{},close=True)
                    with b.db() as con:
                        final_status=con.execute('SELECT status FROM leases WHERE request_id=?',(request_id,)).fetchone()[0]
                    if final_status!='closed':raise ValueError('retirement not reconciled')
                    if network_default:
                        with b.db() as con:
                            facts=[json.loads(row[0]) for row in con.execute('SELECT receipt FROM worker_policy_observations WHERE request_id=?',(request_id,))]
                        if (not facts or any(f['normalized_differences'] for f in facts)
                                or not any(f['docker_status']=='running' for f in facts)
                                or any(f['worker_image']!=image or f['delivery_approval'] is not False for f in facts)):
                            raise ValueError('durable original policy observations missing or divergent')
                        result.update(durable_policy_observations=True,
                            observed_omitted_false=any(f['omitted_false_network_flag'] for f in facts),
                            policy_source_sha256=hashlib.sha256(Path(acp_startup.__file__).with_name('worker_creation_intent.py').read_bytes()).hexdigest())
                    result['lease_status']=final_status
                    result['retirement_observed']=True
                    receipt.write_text(json.dumps(result,sort_keys=True))
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True)
    parser.add_argument('--installed-controller',action='store_true')
    parser.add_argument('--network-default',action='store_true')
    arguments=parser.parse_args()
    print(json.dumps(run(arguments.image,arguments.installed_controller,arguments.network_default),sort_keys=True))
