"""Continuous native integration from an approved S2 fixture, zero model calls.

Only GitHub transport and the preceding TDD decisions are synthetic. Actual
Runtime workers own publication, native timed wakes, Git, Docker/QA and handoff.
This is not real CI, model judgement, release acceptance or a migration.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from fixtures.github_transport import FakeGitHub
from fabriquinha.deployment import Deployment
from fabriquinha.effects import write_json
from fabriquinha.executor import docker
from fabriquinha.kanban_lane import native
from fabriquinha.publication import Repository
from fabriquinha.runtime import Runtime, Owner, worker_alive, recorded_worker
from qualify_hermes_s2 import qualify


class FileGitHub(FakeGitHub):
    """Test transport survives actual worker processes; not installed at runtime."""
    def __init__(self,repo,root,actor):
        super().__init__(repo,native=True,assignee=actor)
        self.root,self.path=Path(root),Path(root)/'github-fixture/state.json'
        value=json.loads(self.path.read_bytes()) if self.path.exists() else {}
        self.pr=value.get('pr');self.calls=value.get('calls',self.calls)
        self.api_calls=value.get('api_calls',0);self.lost_create=value.get('lost_create',False)
        self.ok=(self.root/'github-fixture/ci-ready.json').exists()

    def save(self):
        write_json(self.path,dict(pr=self.pr,calls=self.calls,api_calls=self.api_calls,lost_create=self.lost_create))

    def api(self,*args,**kwargs):
        value=super().api(*args,**kwargs);self.save();return value

    def create(self,*args):
        value=super().create(*args)
        if not self.lost_create:
            self.lost_create=True;self.save()
            raise TimeoutError('fixture PR accepted, confirmation lost')
        self.save();return value

    def merge(self,*args):
        value=super().merge(*args);self.save();return value


class FixtureRuntime(Runtime):
    def integration_services(self,run):
        if not self.project.qualification:raise ValueError('fixture cannot be used in production')
        repo=Repository(self.project,self.store,remote=self.root/'github-fixture/remote.git')
        github=FileGitHub(repo,self.root,run.actor)
        import hermes_cli.kanban_pr_acceptance as gate
        gate._api=github.api  # Test-only transport; native matching/gates remain real.
        return repo,github

    def spawn(self,*args,**kwargs):
        original=subprocess.Popen
        def spawn(command,**options):
            if command[1:4]==['-m','fabriquinha.runtime','worker']:
                command=[command[0],str(Path(__file__).resolve()),'--mode','worker',*command[4:]]
            return original(command,**options)
        # Exercise the actual production spawn/identity code; only select this
        # fixture's worker entry to install its local GitHub transport.
        with patch('fabriquinha.runtime.subprocess.Popen',spawn):
            return super().spawn(*args,**kwargs)


def retire_fixture(root,upstream):
    """Exact owned deployment only, after all claims/effects/workers have settled."""
    with Owner(root):
        runtime=FixtureRuntime(root,upstream);_,kbc,_=native()
        with kbc.connect_closing() as conn:
            rows=conn.execute('SELECT * FROM task_runs').fetchall()
            if any(row['ended_at'] is None for row in rows):raise ValueError('open fixture claim; preserve resources')
            for row in rows:
                spawned=conn.execute("SELECT 1 FROM task_events WHERE run_id=? AND kind IN ('spawned','worker_registered')",(row['id'],)).fetchone()
                if spawned and worker_alive(recorded_worker(conn,row)):raise ValueError('fixture worker still alive')
        for path in (runtime.store.root/'effects').glob('*.json'):
            value=json.loads(path.read_bytes())
            if value.get('state')!='done':raise ValueError('unsettled Docker/Git effect; preserve resources')
        delivery=Deployment(runtime.project,runtime.store,runtime.board,None)
        current=delivery.service()
        if current is None:raise ValueError('no uniquely owned fixture deployment to retire')
        folder=runtime.store.root/'retirement';folder.mkdir(mode=0o700,exist_ok=True)
        write_json(folder/'deployment.json',current)
        write_json(folder/'deployment-logs.json',{'output':docker('logs',current['container'])[:1024*1024]})
        if delivery.service()!=current:raise ValueError('fixture deployment changed before retirement')
        docker('stop','--time','5',current['container'])
        stopped=json.loads(docker('inspect',current['container']))[0]
        labels=stopped['Config'].get('Labels',{})
        if (stopped['State']['Running'] or stopped['Image']!=current['image']
                or labels.get('fabriquinha.project')!=runtime.project.fingerprint()
                or labels.get('com.docker.compose.project')!=delivery.group):
            raise ValueError('owned stopped fixture identity changed')
        docker('rm',current['container'])
        networks=[]
        for suffix in ('default','qa'):
            ident=docker('network','ls','-q','--filter','name=^'+delivery.group+'_'+suffix+'$').strip()
            if not ident:continue
            value=json.loads(docker('network','inspect',ident))[0]
            if (value['Name']!=delivery.group+'_'+suffix or value.get('Containers')
                    or value.get('Labels',{}).get('com.docker.compose.project')!=delivery.group):
                raise ValueError('network still in use or not owned; preserve it')
            write_json(folder/('network-'+suffix+'.json'),dict(id=value['Id'],name=value['Name']))
            docker('network','rm',value['Id']);networks.append(value['Id'])
        if docker('ps','-aq','--filter','label=com.docker.compose.project='+delivery.group).strip():
            raise ValueError('unexpected fixture deployment remains; inspect without repeating deletion')
        write_json(folder/'receipt.json',dict(container=current['container'],networks=networks,
            images_preserved=True,volumes_deleted=0,snapshots_preserved=True))


def integrate(project,store,board,quality,implementation,review,frozen,*,upstream):
    root=store.root.parent;folder=root/'github-fixture';folder.mkdir(mode=0o700)
    remote,seed=folder/'remote.git',folder/'seed';remote.mkdir()
    baseline=store.receipt(frozen,kind='tests_frozen')['payload']['baseline'];store.checkout(baseline,seed)
    def git(path,*args):
        return subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(path),*args],
            check=True,text=True,capture_output=True,timeout=30).stdout
    git(remote,'init','--bare','--initial-branch=main');git(seed,'init','--initial-branch=main')
    git(seed,'add','.')
    git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false',
        'commit','-m','Passing infrastructure fixture baseline')
    git(seed,'remote','add','origin',str(remote));git(seed,'push','origin','HEAD:refs/heads/'+project.branch)
    write_json(root/'project.json',dict(version=1,**{name:dict(value) if name=='reviewers' else value
        for name in project.__dataclass_fields__ for value in (getattr(project,name),) if value is not None}))
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:9/v1',api_key='unused-fixture',
        model='unused-integration-fixture',provider='custom',api_mode='chat_completions'))
    work=root/'integration';work.mkdir(mode=0o700)
    kb,kbc,_=native()
    with kbc.connect_closing() as conn:
        task=kb.create_task(conn,title='Continuous integration fixture; not a release',assignee='s2-devops',
            body=json.dumps(dict(version=1,kind='integration',release='s2-fixture',
                inputs={'delivery':'parent:'+implementation+':delivery'})),parents=[implementation],
            workspace_kind='dir',workspace_path=str(work),max_retries=2,max_runtime_seconds=600,
            completion_contract=project.repository.removeprefix('https://github.com/'))
    services=[]
    def start():
        with os.fdopen(os.open(root/('integration-service-'+str(len(services)+1)+'.log'),
                               os.O_CREAT|os.O_WRONLY,0o600),'wb') as log:
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--mode','serve',
                '--root',str(root),'--upstream',str(upstream)],stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        services.append(process);return process
    def stop(process):
        if process.poll() is None:process.send_signal(signal.SIGTERM)
        process.wait(timeout=15);assert process.returncode==0
    def observed():
        with kbc.connect_closing() as conn:
            return kb.get_task(conn,task),[dict(recorded_worker(conn,row) if row['ended_at'] is not None else row) for row in conn.execute(
                'SELECT * FROM task_runs WHERE task_id=? ORDER BY id',(task,)).fetchall()]
    def until(predicate,service):
        started=time.monotonic();reported=False
        while True:
            card,runs=observed()
            if predicate(card,runs):return card,runs
            if service.poll() is not None:raise RuntimeError('native integration service stopped')
            if card.status in ('blocked','triage'):raise RuntimeError('integration failed; preserve worker logs and evidence')
            if time.monotonic()-started>120 and not reported:
                print('Still observing the same live native integration service.',flush=True);reported=True
            if time.monotonic()-started>480:raise TimeoutError('bounded fixture observation exceeded; do not restart workers')
            time.sleep(0.2)
    service=start()
    try:
        card,runs=until(lambda card,runs:card.status=='scheduled'
            and sum(run['outcome']=='scheduled' for run in runs)>=2
            and all(run['ended_at'] is not None and not worker_alive(run) for run in runs),service)
        assert card.current_run_id is None
        with kbc.connect_closing() as conn:
            assert conn.execute('SELECT COUNT(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]==0
        state=json.loads((folder/'state.json').read_bytes())
        assert state['calls']=={'create':1,'merge':0}
        wait_runs=[run['id'] for run in runs]
        stop(service)
        write_json(folder/'ci-ready.json',{'synthetic_checks_green':True})
        service=start()
        card,runs=until(lambda card,runs:card.status=='done' and all(
            run['ended_at'] is not None and not worker_alive(run) for run in runs),service)
        stop(service)
        assert len(services)==2 and all(process.returncode==0 for process in services)
        latest=kb.latest_run
        with kbc.connect_closing() as conn:
            done=latest(conn,task);key=done.metadata['release_evidence']
            assert done.profile=='s2-qa' and done.outcome=='completed'
            assert conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='respawn_guarded'",(task,)).fetchone()[0]==0
            acceptance=json.loads(conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='pr_acceptance' ORDER BY id DESC LIMIT 1",(task,)).fetchone()[0])
            assert acceptance['ok']
        evidence=store.receipt(key,kind='release_evidence');data=evidence['payload']
        assert data['qualification'] and not data['delivery_approval'] and data['rollback_verified']
        assert evidence['binding']['actor']=='s2-qa' and evidence['binding']['author']=='s2-devops'
        state=json.loads((folder/'state.json').read_bytes());assert state['calls']=={'create':1,'merge':1}
        assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
        assert all(not worker_alive(run) for run in runs)
        result=dict(qualification=True,automatic_wake_loop=True,dispatcher_restarted_while_waiting=True,
            waiting_runs=wait_runs,runs=len(runs),lost_create_ack_did_not_duplicate=True,
            native_pr_gate=True,real_git=True,real_compose=True,real_browser=True,real_rollback=True,
            deployment=dict(release_evidence=key,commit=data['commit'],image=data['image'],
                container=data['container'],url=data['url'],checks=data['checks']),
            model_calls=0,real_github_ci=False,delivery_approval=False,migration=False)
        write_json(root/'integration-receipt.json',result)
        retire_fixture(root,upstream)
        result['deployment']['retired_after_evidence']=True
        return result
    finally:
        if service.poll() is None:stop(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('qualify','serve','worker'),default='qualify')
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image');parser.add_argument('--browser-image')
    parser.add_argument('--task');parser.add_argument('--run',type=int)
    args=parser.parse_args();root=args.root.resolve();upstream=args.upstream.resolve()
    if args.mode=='qualify':
        qualify(root,upstream,args.image,browser_image=args.browser_image,namespace='delivery-kit-hermes-integrate',
            after_review=lambda *values:integrate(*values,upstream=upstream))
    elif args.mode=='worker':
        signal.signal(signal.SIGTERM,lambda *_:sys.exit(143))
        FixtureRuntime(root,upstream).worker(args.task,args.run)
    else:
        with Owner(root):
            runtime=FixtureRuntime(root,upstream);stop=threading.Event()
            for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stop.set())
            runtime.serve(stop,interval=0.25)
