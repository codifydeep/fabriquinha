"""Brief -> reviewed DAG -> two dependent increments -> exact deployed evidence.

Real SDK, native lifecycle, Git, TDD, Docker, browser and release acceptance.
Authors/reviewers and GitHub transport are programmed fixtures, NOT autonomy.
"""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import sqlite3
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from qualify_hermes_s1 import prepare
from qualify_hermes_agent import check_dependencies
from qualify_hermes_integration import FileGitHub,retire_fixture
from fixtures.github_transport import FakeGitHub
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.publication import Repository
from fabriquinha.runtime import Runtime,Owner,worker_alive,recorded_worker


def wal_probe(root):
    """Deterministically reproduce native preflight TOCTOU, then retain WAL."""
    from hermes_state_repair import preflight_db_writability
    path=root/'wal-lifetime-probe.db';wal=Path(str(path)+'-wal');access=os.access
    connection=sqlite3.connect(path);connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE probe(value)');connection.execute('INSERT INTO probe VALUES(1)');connection.commit()
    assert wal.is_file();closed=[False]
    def losing(file,mode):
        if Path(file)==wal and not closed[0]:connection.close();closed[0]=True;assert not wal.exists()
        return access(file,mode)
    with patch('hermes_state_repair.os.access',losing):
        try:preflight_db_writability(path)
        except sqlite3.OperationalError as error:assert str(wal) in str(error)
        else:raise AssertionError('native disappearing-sidecar race was not reproduced')
    keeper=sqlite3.connect(path);keeper.execute('SELECT value FROM probe').fetchone()
    short=sqlite3.connect(path);short.execute('SELECT value FROM probe').fetchone();closed[0]=False
    def retained(file,mode):
        if Path(file)==wal and not closed[0]:short.close();closed[0]=True;assert wal.is_file()
        return access(file,mode)
    with patch('hermes_state_repair.os.access',retained):preflight_db_writability(path)
    assert keeper.execute('SELECT value FROM probe').fetchone()==(1,);keeper.close()
    value=dict(native_race_reproduced=True,connection_lifetime_retains_wal=True,data_preserved=True,upstream_patches=0)
    write_json(root/'wal-lifetime-probe.json',value);return value


class PackageGitHub(FileGitHub):
    def __init__(self,repo,root,actor,task):
        self.number=int(task.removeprefix('t_'),16)+1
        folder=Path(root)/'package-ci'/task
        write_json(folder/'github-fixture/ci-ready.json',{'fixture':True})
        super().__init__(repo,folder,actor)

    def create(self,*args):
        result=FakeGitHub.create(self,*args)
        self.pr['url']=self.repo.project.repository+'/pull/'+str(self.number)
        self.save();return dict(self.pr)


class FixtureRuntime(Runtime):
    def release_services(self,actor,*,task=None):
        if not self.project.qualification:raise ValueError('local fixture only')
        repo=Repository(self.project,self.store,remote=self.root/'github-fixture/remote.git')
        if task is None:return repo,None
        github=PackageGitHub(repo,self.root,actor,task)
        import hermes_cli.kanban_pr_acceptance as gate
        gate._api=github.api
        return repo,github

    def integration_services(self,run):
        fault=self.root/'recovery-mode.json';marker=self.root/'integration-fault.json'
        if self.project.qualification and fault.exists() and json.loads(fault.read_bytes())['mode']=='recover' and not run.reviewing:
            try:fd=os.open(marker,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError:pass
            else:
                with os.fdopen(fd,'w') as f:json.dump({'run':run.number},f)
                raise ValueError('Injected pre-publication integration precondition failure; no external effect was sent')
        return self.release_services(run.actor,task=run.task)

    def spawn(self,*args,**kwargs):
        original=subprocess.Popen
        def spawn(command,**options):
            if command[1:4]==['-m','fabriquinha.runtime','worker']:
                command=[command[0],str(Path(__file__).resolve()),'--mode','worker',*command[4:]]
            return original(command,**options)
        with patch('fabriquinha.runtime.subprocess.Popen',spawn):return super().spawn(*args,**kwargs)


def qualify(root,upstream,image,browser,*,namespace='delivery-kit-hermes-release',recovery='none'):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(mode=0o700,parents=True);check_dependencies();home=prepare(root,upstream)
    os.environ['HERMES_DISABLE_LAZY_INSTALLS']='1';kb,kbc,_=native()
    with kbc.connect_closing():pass
    wal=wal_probe(root)
    from hermes_cli.profiles import create_profile
    for role in ('product','lead','cto','tests','author','devops'):
        name='release-'+role;create_profile(name,no_skills=True,description='Programmed end-to-end release qualification')
        write_json(home/'profiles'/name/'config.yaml',dict(model={'streaming':False,'context_length':65536},
            auxiliary={'title_generation':{'enabled':False}},tools={'tool_search':{'enabled':'off'}},
            terminal={'backend':'fabriquinha','cwd':'/workspace'}))
    write_json(root/'project.json',dict(version=1,namespace=namespace,
        repository='https://github.com/example/release-qualification',branch='release/qualification',
        validation_image=image,browser_image=browser,tests_dir='tests',qualification=True,
        coordination_roles={'product':'release-product','lead':'release-lead'},
        technical_roles={'lead':'release-lead','cto':'release-cto'},
        delivery_roles={'tests':'release-tests','integration':'release-devops'},
        reviewers={'release-tests':'release-lead','release-author':'release-lead','release-lead':'release-cto','release-devops':'release-tests'}))
    runtime=FixtureRuntime(root,upstream)
    if recovery!='none':write_json(root/'recovery-mode.json',dict(mode=recovery))
    fixture=ROOT/'tests/fixtures/delivery';folder=root/'github-fixture';folder.mkdir(mode=0o700)
    remote,seed=folder/'remote.git',folder/'seed';remote.mkdir();shutil.copytree(fixture/'base',seed)
    def git(path,*args):
        return subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(path),*args],check=True,capture_output=True,text=True,timeout=30).stdout
    git(remote,'init','--bare','--initial-branch=main');git(seed,'init','--initial-branch=main');git(seed,'add','.')
    git(seed,'-c','user.name=Qualification','-c','user.email=qualification@example.invalid','-c','commit.gpgsign=false','commit','-m','Passing infrastructure baseline only')
    git(seed,'remote','add','origin',str(remote));git(seed,'push','origin','HEAD:refs/heads/release/qualification')
    started=runtime.intake.start(dict(request='two-increments',label='v0.1',objective='A local greeting page, then add a farewell without breaking the greeting.'))
    brief=dict(summary='Two visible HTTP behaviors.',criteria=[dict(id='GREET',statement='Greet Ada by name.'),dict(id='BYE',statement='Say goodbye to Ada.')],
        assumptions=['Local anonymous use'],out_of_scope=['Mobile'],observability='Count failed requests without storing names.')
    document=dict(architecture='Python HTTP with small DOM controls.',observability='Record HTTP error totals.',tasks=[
        dict(id='greet',title='Named greeting',owner='release-author',depends_on=[],criteria=['GREET'],acceptance='Click greet to see Hello, Ada'),
        dict(id='farewell',title='Named farewell',owner='release-author',depends_on=['greet'],criteria=['BYE'],acceptance='Click farewell to see Goodbye, Ada; greeting remains intact')])
    app1=(fixture/'app_feature.py').read_text()
    app2=app1.replace('<p id="result" role="status"></p>',
        '<button id="farewell">Farewell</button><p id="farewell-result" role="status"></p><p id="result" role="status"></p>')
    app2=app2.replace('</script>',"document.querySelector('#farewell').onclick=async()=>{const r=await fetch('/farewell?name='+encodeURIComponent(document.querySelector('#name').value));document.querySelector('#farewell-result').textContent=(await r.json()).message;};</script>")
    app2=app2.replace("        elif url.path == '/':", "        elif url.path == '/farewell':\n            status, value = 200, {'message': 'Goodbye, '+parse_qs(url.query).get('name', ['World'])[0]}\n        elif url.path == '/':")
    test1=(fixture/'test_greeting.py').read_text()
    test2=test1.replace('Greeting','Farewell').replace('test_named_greeting','test_named_farewell').replace('/greeting?','/farewell?').replace('Hello, Ada','Goodbye, Ada')
    sequences={};requests={};bindings={};plan_faults=[];diagnostic_actions=[];guidance_seen=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            marker=next((m['content'].splitlines()[0] for m in reversed(body['messages']) if m.get('role')=='user'
                and isinstance(m.get('content'),str) and m['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):self.send_error(400);return
            binding=json.loads(marker.removeprefix('Delivery activity '));run=runtime.board.current(binding['task'],binding['number'])
            assert run.binding()==binding;bindings[run.number]=binding
            if run.number not in sequences:
                if run.kind=='diagnostic':
                    context=runtime.store.receipt(runtime.board.input(run,'incident'),kind='incident')
                    payload=context['payload'];source=context['binding']['kind']
                    action=('hold' if not payload['resume_allowed'] else 'escalate'
                            if source=='integration' and run.actor=='release-lead' else 'resume')
                    reason='Repair the review protocol before any new attempt; keep native triage unchanged.' if action=='hold' else 'The fixed validation identifies a resumable precondition; follow the original phase.'
                    decision=dict(action=action,reason=reason,findings=[dict(evidence='experiment',detail='Use this verified technical guidance without changing tests or delivery evidence.')])
                    sequence=[('diagnostic_validate',{'hypothesis':'Check the recorded plan contract' if source=='plan' else 'Check the approved application suite'}),
                        ('diagnostic_decide',decision)]
                    if action=='hold':sequence.insert(0,('diagnostic_decide',{**decision,'action':'resume'}))
                    diagnostic_actions.append((source,action,run.number))
                elif run.kind=='brief':sequence=[('brief_submit',brief)]
                elif run.kind=='plan' and run.reviewing and recovery!='none' and (recovery=='triage' or not plan_faults):
                    plan_faults.append(run.number);sequence=[(None,'I will review this plan later.')]
                    write_json(root/'plan-faults.json',dict(runs=plan_faults))
                elif run.kind=='plan':sequence=[('plan_review',dict(decision='approve',reason='Independent fixture architecture review',findings=[]))] if run.reviewing else [('plan_submit',document)]
                elif run.reviewing:sequence=[('delivery_review',dict(decision='approve',reason='Independent immutable fixture review',findings=[]))]
                else:
                    with kbc.connect_closing() as conn:package=json.loads(kb.get_task(conn,run.task).body)['package']
                    first=package=='greet';app=app1 if first else app2
                    if run.kind=='tests':
                        check=dict(id='GREET' if first else 'BYE',path='/',actions=[dict(action='fill',selector='#name',value='Ada'),
                            dict(action='click',selector='#greet' if first else '#farewell')],
                            selector='#result' if first else '#farewell-result',text='Hello, Ada' if first else 'Goodbye, Ada')
                        sequence=[('write_file',dict(path='/workspace/tests/test_'+package+'.py',content=test1 if first else test2)),
                            ('write_file',dict(path='/workspace/tests/qa.'+package+'.json',content=json.dumps(dict(version=1,checks=[check])))),('delivery_submit',{})]
                    else:sequence=[('write_file',dict(path='/workspace/app.py',content=app)),
                        ('delivery_submit',{'mutations':[{'app.py':app.replace('Hello, ','Wrong, ') if first else app.replace('Goodbye, ','Wrong, ')}]})]
                sequences[run.number]=sequence
                if recovery!='none' and run.kind=='plan' and run.reviewing and sequence[0][0]=='plan_review':
                    assert 'Controller-recorded diagnostic guidance' in str(body['messages'])
                    guidance_seen.append(run.number)
            index=requests.get(run.number,0);requests[run.number]=index+1
            if index>=len(sequences[run.number]):self.send_error(400);return
            name,args=sequences[run.number][index]
            message=(dict(role='assistant',content=None,tool_calls=[dict(id='release-'+str(run.number)+'-'+str(index),
                type='function',function=dict(name=name,arguments=json.dumps(args)))]) if name else dict(role='assistant',content=args))
            value=dict(id='local-'+str(run.number)+'-'+str(index),object='chat.completion',created=int(time.time()),model=body['model'],
                choices=[dict(index=0,finish_reason='tool_calls' if name else 'stop',message=message)],
                usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150))
            data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Response);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',api_key='local-fixture',
        provider='custom',api_mode='chat_completions',model='fabriquinha-release-fixture'))
    services=[]
    def start():
        with os.fdopen(os.open(root/('service-'+str(len(services)+1)+'.log'),os.O_CREAT|os.O_WRONLY,0o600),'wb') as log:
            service=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--mode','serve','--root',str(root),'--upstream',str(upstream)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        services.append(service);return service
    service=start()
    def until(predicate,seconds=480):
        began=time.monotonic()
        while not predicate():
            if service.poll() is not None:raise RuntimeError('release service stopped')
            status=json.loads((root/'status.json').read_bytes()) if (root/'status.json').exists() else {}
            board=status.get('board',{})
            with kbc.connect_closing() as conn:
                blocked={r[0] for r in conn.execute("SELECT id FROM task_runs WHERE outcome IN ('blocked','crashed','timed_out')")}
            expected=set(plan_faults)
            if (root/'integration-fault.json').exists():expected.add(json.loads((root/'integration-fault.json').read_bytes())['run'])
            if blocked-expected or board.get('release_issues') or board.get('intake_issues') or board.get('recovery_issues'):
                write_json(root/'failure-observation.json',status)
                raise RuntimeError('release failed; inspect preserved evidence')
            if time.monotonic()-began>seconds:raise TimeoutError('observation expired; inspect same live handles, never restart on timeout')
            time.sleep(0.2)
    try:
        pending=[None]
        def question():
            with kbc.connect_closing() as conn:
                for card in conn.execute("SELECT id FROM tasks WHERE assignee='fabriquinha-ceo' AND status='review'"):
                    pending[0]=runtime.intake.pending(conn,card['id']);return pending[0]
        until(question);assert pending[0]['kind']=='product_brief'
        runtime.intake.respond(pending[0]['task'],pending[0]['request'],'approve','Approve this exact fixture business scope only')
        def delivered():
            with kbc.connect_closing() as conn:return runtime.intake.terminal(kb.get_task(conn,started['release']))
        def settled():
            with kbc.connect_closing() as conn:
                for row in conn.execute('SELECT * FROM task_runs'):
                    event=conn.execute("SELECT 1 FROM task_events WHERE run_id=? AND kind IN ('spawned','worker_registered')",(row['id'],)).fetchone()
                    if event and (not row['ended_at'] or worker_alive(recorded_worker(conn,row))):return False
            return True
        if recovery=='triage':
            until(lambda:any(i['state']=='held' for i in runtime.status()['incidents']))
            until(settled);assert len(plan_faults)==2
            with kbc.connect_closing() as conn:
                source=kb.get_task(conn,bindings[plan_faults[-1]]['task'])
                assert source.status=='triage' and source.block_recurrences==2
                for number in plan_faults:
                    event=conn.execute("SELECT payload FROM task_events WHERE run_id=? AND kind='claimed'",(number,)).fetchone()
                    assert json.loads(event[0])['source_status']=='review'
            service.send_signal(signal.SIGTERM);service.wait(timeout=15);assert service.returncode==0
            count=sum(requests.values());service=start()
            until(lambda:any(i['state']=='held' for i in runtime.status()['incidents']))
            time.sleep(1.5)
            assert sum(requests.values())==count and not delivered()
            with kbc.connect_closing() as conn:
                source=kb.get_task(conn,source.id);assert source.status=='triage' and source.block_recurrences==2
            service.send_signal(signal.SIGTERM);service.wait(timeout=15);assert service.returncode==0
            runtime.pause()
            with kbc.connect_closing() as conn:assert runtime.pause_status(conn)['drained']
            assert [(kind,action) for kind,action,_ in diagnostic_actions]==[('plan','resume'),('plan','hold')]
            result=dict(passed=True,scenario='native_triage_owned_hold',review_phase_preserved=True,
                native_breaker_not_reset=True,unsupported_resume_denied=True,hold_survived_restart_without_new_calls=True,
                automatic_cto_assignment=True,source_review_failures=2,local_http_requests=count,
                release_homologated=False,paid_calls=0,model_judgment=False,delivery_approval=False)
            write_json(root/'receipt.json',result);return result
        until(delivered)
        until(settled);service.send_signal(signal.SIGTERM);service.wait(timeout=15);assert service.returncode==0
        with kbc.connect_closing() as conn:
            anchor=kb.get_task(conn,started['release']);row=kb.latest_run(conn,anchor.id)
            acceptance=runtime.store.receipt(row.metadata['release_acceptance'],kind='release_acceptance')
            data=acceptance['payload'];assert data['state']=='HOMOLOGADA' and not data['delivery_approval']
            graph=runtime.store.receipt(data['graph'],kind='release_graph')['payload'];assert len(graph['items'])==2
            assert data['packages'][1]['cases'] and set(data['packages'][0]['cases'])<set(data['packages'][1]['cases'])
            assert data['packages'][0]['commit']!=data['packages'][1]['commit']
            assert set(data['criteria'])=={'GREET','BYE'} and len({p['pr'] for p in data['packages']})==2
            assert all(kb.get_task(conn,c['id']).status=='done' for i in graph['items'] for c in i['cards'].values())
        runtime.pause()
        result=dict(passed=True,synthetic_authors=True,real_github_ci=False,paid_calls=0,model_judgment=False,
            sdk_activities=len(requests),local_http_requests=sum(requests.values()),work_packages=2,generated_work_cards=6,
            branch_bases_chained=True,old_tests_preserved=True,final_criteria=data['criteria'],
            release_gate_exercised=True,delivery_approval=False,migration=False,url=data['url'])
        result['wal_lifetime_probe']=wal
        if recovery=='recover':
            assert len(plan_faults)==1 and len(guidance_seen)==1
            assert [(kind,action) for kind,action,_ in diagnostic_actions]==[('plan','resume'),('integration','escalate'),('integration','resume')]
            assert all(i['state']=='resolved' for i in runtime.status()['incidents'])
            result.update(planning_review_recovered_without_phase_loss=True,integration_recovered_by_lead_cto=True,complete_diagnostic_guidance=True)
        write_json(root/'chain-receipt.json',result)
        retire_fixture(root,upstream)
        result['deployment_retired_after_evidence']=True
        write_json(root/'receipt.json',result);return result
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        if service.poll() is None:runtime.pause()  # Preserve live workers/claims for verified drain.


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=('qualify','serve','worker','retire'),default='qualify')
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image');parser.add_argument('--browser-image');parser.add_argument('--task');parser.add_argument('--run',type=int)
    parser.add_argument('--namespace',default='delivery-kit-hermes-release')
    parser.add_argument('--recovery',choices=('none','recover','triage'),default='none')
    args=parser.parse_args();root,upstream=args.root.resolve(),args.upstream.resolve()
    if args.mode=='worker':FixtureRuntime(root,upstream).worker(args.task,args.run)
    elif args.mode=='serve':
        with Owner(root):
            stop=threading.Event()
            for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stop.set())
            FixtureRuntime(root,upstream).serve(stop,interval=0.25)
    elif args.mode=='retire':retire_fixture(root,upstream)
    else:
        try:print(json.dumps(qualify(root,upstream,args.image,args.browser_image,namespace=args.namespace,recovery=args.recovery),indent=2))
        except BaseException as error:
            write_json(root/'failure.json',dict(category=type(error).__name__,message=str(error)[:2000],delivery_approval=False));raise
