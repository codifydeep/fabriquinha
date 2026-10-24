"""Single continuous dispatcher, detached SDK workers, native lifecycle only.

Operational slice: TDD and native technical diagnostics. Product publication/
deployment are not yet attached. Paid providers stay paused.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .artifacts import Store, digest
from .board import Board
from .config import Project
from .effects import EffectBlocked, Pending, write_json
from .executor import Runner
from .hermes import Sandbox, run_activity
from .kanban_lane import native, UPSTREAM_COMMIT
from .quality import Quality
from .recovery import Recovery
from .notifications import Outbox, alerts, validation_progress


def bind(root,upstream):
    if subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()!=UPSTREAM_COMMIT:
        raise ValueError('pinned Hermes upstream required')
    if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip():
        raise ValueError('unmodified Hermes checkout required')
    sys.path.insert(0,str(upstream))
    os.environ.update(HERMES_HOME=str(root/'home'),HERMES_KANBAN_DB=str(root/'home/kanban.db'),
        HERMES_KANBAN_BOARD='default',HERMES_DISABLE_LAZY_INSTALLS='1',PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1]),str(upstream)]))


@contextmanager
def Owner(root):
    """One service owner; the upstream dispatcher also locks each tick."""
    with (Path(root)/'runtime.lock').open('a') as file:
        fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:fcntl.flock(file,fcntl.LOCK_UN)


def model_route(project,path):
    # The old financial pause is not lifted by installing an adapter. Wire the
    # metered, explicitly released provider before enabling production here.
    if not project.qualification:
        raise ValueError('real provider release is not yet installed; paid execution remains disabled')
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('private controller route file required')
    route=json.loads(path.read_bytes())
    from urllib.parse import urlsplit
    if not isinstance(route,dict) or not isinstance(route.get('base_url'),str):
        raise ValueError('explicit qualification route required')
    url=urlsplit(route['base_url'])
    if url.scheme!='http' or url.hostname!='127.0.0.1' or url.username or url.password:
        raise ValueError('qualification route must be loopback only')
    return route


def worker_alive(row):
    kb,_,dispatch=native()
    if not (row['claim_lock'] or '').startswith(kb._host_prefix()) or not row['worker_pid']:
        raise EffectBlocked('native worker identity is not verified on this host')
    return dispatch._worker_alive(row['worker_pid'],row['worker_started_at'])


class Runtime:
    def __init__(self,root,upstream):
        self.root,self.upstream=Path(root).resolve(),Path(upstream).resolve()
        bind(self.root,self.upstream)
        self.project=Project.parse(json.loads((self.root/'project.json').read_bytes()))
        binding=dict(project=self.project.fingerprint(),upstream=UPSTREAM_COMMIT)
        installation=self.root/'installation.json'
        if installation.exists() and json.loads(installation.read_bytes())!=binding:
            raise ValueError('installation contract changed; explicit reconfiguration required')
        if not installation.exists():write_json(installation,binding)
        self.store=Store(self.root/'private');self.board=Board(self.project)
        self.children=[];self.settlement={};self.recovery_issues={}
        self.recovery=Recovery(self.project,self.store,self.board)
        self.outbox=Outbox(self.project,self.store)

    def settle(self,task=None,*,conn=None):
        """Retire only stale SDK sandboxes; no process is killed here.

        Called globally before dispatch and again for the specific task before
        spawn, so a dead process cannot leave a writable container beside its
        replacement. Uncertain effects keep their original journal identities.
        """
        if conn is None:
            _,kbc,_=native()
            with kbc.connect_closing() as connection:return self.settle(task,conn=connection)
        if task is None:self.settlement={}
        else:self.settlement.pop(task,None)
        for path in (self.store.root/'effects').glob('*.json'):
            state=json.loads(path.read_bytes());identity=state.get('identity',{})
            if not isinstance(identity,dict) or set(identity)!={'binding','project','workspace','phase','baseline_tests','image'}:continue
            key=digest(identity);binding=identity['binding']
            if path.name!=digest(key+':agent-create')+'.json' or task and binding['task']!=task:continue
            if (self.store.root/'agents'/key/'retirement.json').exists():continue
            try:
                row=conn.execute('SELECT * FROM task_runs WHERE id=?',(binding['number'],)).fetchone()
                if not row or row['task_id']!=binding['task'] or row['profile']!=binding['actor']:
                    raise EffectBlocked('sandbox intent has no matching native run')
                if row['ended_at'] is None:
                    if task:raise EffectBlocked('prior sandbox still belongs to an open native run')
                    continue
                if worker_alive(row):
                    raise EffectBlocked('prior SDK worker still alive; preserve its sandbox')
                Sandbox.recover(self.project,self.store,identity).close()
            except (Pending,EffectBlocked,ValueError,subprocess.SubprocessError) as error:
                self.settlement[binding['task']]=dict(run=binding['number'],category=type(error).__name__)
                if task:raise
        return self.settlement

    def spawn(self,task,workspace,*,board=None):
        self.settle(task.id)
        folder=self.root/'runs'/str(task.current_run_id);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        env={key:os.environ[key] for key in ('PATH','PYTHONPATH','HERMES_HOME','HERMES_KANBAN_DB',
             'HERMES_KANBAN_BOARD','HERMES_DISABLE_LAZY_INSTALLS','PYTHONDONTWRITEBYTECODE') if key in os.environ}
        fd=os.open(folder/'worker.log',os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
        with os.fdopen(fd,'ab') as log:
            process=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','worker',
                '--root',str(self.root),'--upstream',str(self.upstream),
                '--task',task.id,'--run',str(task.current_run_id)],stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        self.children.append(process)
        return process.pid

    def tick(self):
        self.children=[child for child in self.children if child.poll() is None]
        # A changed project file cannot silently grant a live service authority.
        if Project.parse(json.loads((self.root/'project.json').read_bytes())).fingerprint()!=self.project.fingerprint():
            raise ValueError('project changed while service was running')
        _,kbc,dispatch=native()
        with kbc.connect_closing() as conn:
            self.settle(conn=conn)
            self.recovery_issues=self.recovery.reconcile(conn,self.settle)
            return dispatch.dispatch_once(conn,spawn_fn=self.spawn,max_spawn=self.project.max_workers,
                max_in_progress=self.project.max_workers,max_in_progress_per_profile=1)

    def status(self):
        _,kbc,_=native()
        with kbc.connect_closing() as conn:
            cards=[dict(row) for row in conn.execute('SELECT id,title,status,assignee,current_run_id,last_heartbeat_at,created_at,body, '
                '(SELECT started_at FROM task_runs WHERE id=tasks.current_run_id) AS run_started_at, '
                '(SELECT MAX(created_at) FROM task_events WHERE task_id=tasks.id) AS last_event_at '
                'FROM tasks ORDER BY created_at')]
            for card in cards:
                raw=card.pop('body')
                try:card['contract']=digest(json.loads(raw or '{}'))
                except ValueError:card['contract']=None
                try:card['last_validation']=validation_progress(card,self.store,self.project)
                except (ValueError,OSError):card['last_validation']={'error':'EvidenceUnavailable'}
            incidents=self.recovery.status(conn)
        return dict(namespace=self.project.namespace,cards=cards,settlement=self.settlement,recovery_issues=self.recovery_issues,
                    incidents=incidents,notifications=self.outbox.summary(),qualification=self.project.qualification,delivery_approval=False)

    def serve(self,stop,*,interval=15):
        if not 0.1<=interval<=60:raise ValueError('bounded dispatch interval required')
        model_route(self.project,self.root/'route.json')
        self.status()  # Validate the read surface before any worker is spawned.
        _,kbc,_=native()
        enabled=threading.Event()
        def capture():
            try:
                with kbc.connect_closing() as conn:self.outbox.capture(conn)
                enabled.set()
            except Exception as error:
                enabled.clear()
                self.outbox.save(self.outbox.root/'error.json',dict(category=type(error).__name__,at=time.time()))
        capture()
        sender=threading.Thread(target=self.outbox.loop,args=(stop,self.root/'notifications.json',enabled),daemon=True)
        sender.start()
        try:
            while not stop.is_set():
                self.tick()
                capture()
                try:
                    alerts(self.outbox,self.status()['cards'],self.store,now=time.time())
                except Exception as error:
                    self.outbox.save(self.outbox.root/'error.json',dict(category=type(error).__name__,at=time.time()))
                write_json(self.root/'status.json',dict(dispatcher_pid=os.getpid(),dispatcher_state='running',observed_at=time.time(),board=self.status()))
                stop.wait(interval)
        finally:
            stop.set();sender.join(timeout=4)
            write_json(self.root/'status.json',dict(dispatcher_pid=os.getpid(),dispatcher_state='stopped',observed_at=time.time(),board=self.status()))
        # Do not terminate healthy detached workers on dispatcher shutdown.

    def worker(self,task,number):
        kb,kbc,dispatch=native();sandbox=None
        with kbc.connect_closing() as conn:
            if not dispatch.adopt_worker_pid(conn,task,number,os.getpid()):
                raise ValueError('native claim lost before worker startup')
            owner=conn.execute('SELECT worker_pid FROM task_runs WHERE id=? AND task_id=?',(number,task)).fetchone()
            if not owner or owner['worker_pid']!=os.getpid():
                raise ValueError('native run belongs to another worker process')
            prompt=kb.build_worker_context(conn,task)
        run=self.board.current(task,number)
        try:
            route=model_route(self.project,self.root/'route.json')
            os.environ['HERMES_HOME']=str(self.root/'home/profiles'/run.actor)
            quality=Quality(self.project,self.store,Runner(self.project,self.store),self.board)
            if run.kind=='implementation' and not run.reviewing:
                work=self.board.workspace(run);frozen=quality.freeze(run,self.board.input(run,'tests'))
                if not any(work.iterdir()):self.store.checkout(frozen['snapshot'],work)
                else:quality.protect(frozen['snapshot'],self.store.capture(work),exact_tests=True)
            sandbox=Sandbox(self.project,self.store,self.board,run)
            prompt='Delivery activity '+json.dumps(run.binding(),sort_keys=True)+'\n'+prompt
            result=run_activity(sandbox,quality,route,prompt)
            write_json(self.root/'runs'/str(number)/'activity.json',dict(binding=run.binding(),result=result))
        except BaseException as error:
            failure=self.store.record('worker_failure',run.binding(),dict(project=self.project.fingerprint(),
                category=type(error).__name__,message=str(error)[:2000]))
            with kbc.connect_closing() as conn:
                kb.block_task(conn,task,reason=json.dumps(dict(category=type(error).__name__,failure=failure)),
                              kind='capability',expected_run_id=number)
            raise
        finally:
            if sandbox:sandbox.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('serve','worker','status'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--task');parser.add_argument('--run',type=int);parser.add_argument('--interval',type=float,default=15)
    args=parser.parse_args()
    if args.operation=='serve':
        with Owner(args.root):
            runtime=Runtime(args.root,args.upstream);stop=threading.Event()
            for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stop.set())
            runtime.serve(stop,interval=args.interval)
    elif args.operation=='worker':
        def terminated(*_):raise SystemExit(143)
        signal.signal(signal.SIGTERM,terminated)
        Runtime(args.root,args.upstream).worker(args.task,args.run)
    else:print(json.dumps(Runtime(args.root,args.upstream).status(),indent=2))


if __name__=='__main__':main()
