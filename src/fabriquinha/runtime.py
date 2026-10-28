"""Single continuous dispatcher, detached SDK workers, native lifecycle only.

TDD/technical diagnostics use isolated SDK workers. Integration uses fixed
publication/deployment/QA operations, never a host shell exposed to a model.
Paid providers require an explicitly enabled private policy and scoped budget.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from .artifacts import Store, digest
from .board import Board
from .config import Project
from .effects import EffectBlocked, Pending, Journal, write_json
from .executor import Runner,seal_validation,validation_files,browser_contract
from .hermes import Sandbox, run_activity
from .kanban_lane import native, UPSTREAM_COMMIT
from .quality import Quality
from .recovery import Recovery, guidance_context
from .notifications import Outbox, alerts, validation_progress
from .publication import Repository, GitHub, Publication
from .deployment import Deployment
from .operations import Control, ActivityPaused, doctor
from .intake import Intake, DraftActivity
from .releases import Releases
from .provider import Policy, Held, inspect as inspect_provider,inspect_usage
from .source import environment as check_source
from .profile_policy import contract as profile_contract,admission as profile_admission,report as profile_report


class IntegrationRunner(Runner):
    """Wait for bounded local computation, not for external CI or model replies."""
    def _execute(self,*args,**kwargs):
        deadline=time.monotonic()+self.project.timeout_seconds+15
        while True:
            try:return super()._execute(*args,**kwargs)
            except Pending:
                if time.monotonic()>=deadline:raise EffectBlocked('local integration job observation expired')
                time.sleep(0.1)


def bind(root,upstream):
    check_source()  # Managed entry verifies again in the actual SDK interpreter.
    if subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()!=UPSTREAM_COMMIT:
        raise ValueError('pinned Hermes upstream required')
    if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip():
        raise ValueError('unmodified Hermes checkout required')
    sys.path.insert(0,str(upstream))
    os.environ.update(HERMES_HOME=str(root/'home'),HERMES_KANBAN_DB=str(root/'home/kanban.db'),
        HERMES_KANBAN_BOARD='default',HERMES_DISABLE_LAZY_INSTALLS='1',PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1]),str(upstream)]))


@contextmanager
def native_keepalive(path,kbc):
    """Bridge a disappearing-WAL preflight race; never chmod, delete or retry.

    A short read transaction protects initialized WAL sidecars until the native
    keeper has opened. Release it before dispatch so checkpoints are not pinned.
    Missing DBs and actual access problems remain with native initialization.
    """
    path=Path(path).absolute();bootstrap=None
    try:
        if path.is_file() and os.access(path,os.R_OK|os.W_OK) and os.access(path.parent,os.R_OK|os.W_OK|os.X_OK):
            bootstrap=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=5)
            if bootstrap.execute('PRAGMA journal_mode').fetchone()[0]=='wal':
                bootstrap.execute('BEGIN')
                bootstrap.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
        with kbc.connect_closing() as keeper:
            keeper.execute('SELECT id FROM tasks LIMIT 1').fetchone()
            if bootstrap:bootstrap.close();bootstrap=None
            yield keeper
    finally:
        if bootstrap:bootstrap.close()


@contextmanager
def Owner(root):
    """One service owner; the upstream dispatcher also locks each tick."""
    with (Path(root)/'runtime.lock').open('a') as file:
        fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:fcntl.flock(file,fcntl.LOCK_UN)


def model_route(project,path,*,require_ready=True):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size>4096:
        raise ValueError('private controller route file required')
    route=json.loads(path.read_bytes())
    from urllib.parse import urlsplit
    if (not isinstance(route,dict) or set(route)!={'base_url','api_key','provider','api_mode','model'}
            or any(not isinstance(value,str) or not value for value in route.values())
            or route['provider']!='custom' or route['api_mode']!='chat_completions'):
        raise ValueError('explicit closed controller route required')
    url=urlsplit(route['base_url'])
    if (url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.username or url.password
            or url.path!='/v1' or url.query or url.fragment):
        raise ValueError('controller route must use fixed loopback /v1')
    policy_path=path.parent/'provider-policy.json'
    if not project.qualification or policy_path.exists() or policy_path.is_symlink():
        if (not policy_path.is_file() or policy_path.is_symlink() or policy_path.stat().st_mode&0o077
                or policy_path.stat().st_size>4096):raise ValueError('private explicit provider policy required')
        policy=Policy.parse(json.loads(policy_path.read_bytes()))
        if policy.project!=project.fingerprint() or route['model']!=policy.model or route['api_key']!=policy.client_token:
            raise ValueError('route must match exact operator provider policy')
        if require_ready:
            if not policy.enabled:raise Held('provider_disabled')
            inspect_provider(policy,'http://127.0.0.1:'+str(url.port),project.fingerprint())
    return route


def worker_alive(row):
    kb,_,dispatch=native()
    if not (row['claim_lock'] or '').startswith(kb._host_prefix()) or not row['worker_pid']:
        # This installation is local-only. macOS may change its hostname when
        # switching networks. A completed historical run may be observed dead
        # with its exact spawn fingerprint; this never reclaims an active claim
        # or authorizes signalling a foreign/possibly-live process.
        if 'ended_at' in row.keys() and row['ended_at'] is not None:
            if (row['worker_pid'] and row['worker_started_at'] not in (None,'unverified')
                    and not dispatch._worker_alive(row['worker_pid'],row['worker_started_at'])):return False
        raise EffectBlocked('native worker identity is not verified on this host')
    return dispatch._worker_alive(row['worker_pid'],row['worker_started_at'])


def recorded_worker(conn,row):
    """Upstream may reap terminal PID fields; its spawn event retains identity."""
    if row['worker_pid'] and row['worker_started_at']:return row
    event=conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind IN ('spawned','worker_registered') ORDER BY id DESC LIMIT 1",
                       (row['task_id'],row['id'])).fetchone()
    data=json.loads(event[0]) if event else {}
    if (not isinstance(data,dict) or type(data.get('pid')) is not int or data['pid']<1 or not data.get('started_at')
            or row['worker_pid'] not in (None,data['pid']) or row['worker_started_at'] not in (None,data['started_at'])):
        raise EffectBlocked('native worker spawn identity unavailable or changed')
    return {**dict(row),'worker_pid':data['pid'],'worker_started_at':data['started_at']}


class Runtime:
    def __init__(self,root,upstream):
        self.root,self.upstream=Path(root).resolve(),Path(upstream).resolve()
        bind(self.root,self.upstream)
        self.project=Project.parse(json.loads((self.root/'project.json').read_bytes()))
        binding=dict(project=self.project.fingerprint(),upstream=UPSTREAM_COMMIT)
        installation=self.root/'installation.json'
        self.store=Store(self.root/'private')
        with Journal(self.store.root/'effects').lock(['installation',self.project.fingerprint()]):
            if installation.exists():
                existing=json.loads(installation.read_bytes())
                if 'validation_bundle' in existing:
                    from .quality import CONTROL_CONTRACT
                    binding.update(validation_bundle=existing['validation_bundle'],control_contract=CONTROL_CONTRACT)
                if 'profile_contract' in existing:binding['profile_contract']=profile_contract()
                if 'browser_contract' in existing:
                    if type(existing['browser_contract']) is not int or existing['browser_contract'] not in (1,2):
                        raise ValueError('known installed browser contract required')
                    binding['browser_contract']=existing['browser_contract']
                if existing!=binding:raise ValueError('installation contract changed; explicit reconfiguration required')
            else:
                from .quality import CONTROL_CONTRACT
                binding.update(validation_bundle=seal_validation(self.store),control_contract=CONTROL_CONTRACT)
                if not self.project.qualification:binding['profile_contract']=profile_contract()
                write_json(installation,binding)
            validation_files(self.project,self.store)
            browser_contract(self.project,self.store)
        self.control=Control(self.root,self.project)
        self.board=Board(self.project,guard=self.control.ensure)
        self.children=[];self.settlement={};self.recovery_issues={};self.integration_issues={}
        self.admission=None;self._next_admission=0
        self.provider=None;self.provider_issues={}
        self.recovery=Recovery(self.project,self.store,self.board)
        self.intake=Intake(self.project,self.store,self.board);self.intake_issues={}
        self.releases=Releases(self.project,self.store,self.board,self.intake);self.release_issues={}
        self.outbox=Outbox(self.project,self.store)

    def disable_provider(self,episode):
        """Persist economic shutdown only after the dispatcher and workers stop."""
        with Owner(self.root):
            control=self.control.read()
            if (not control['paused'] or control.get('error') or control['episode']!=episode):
                raise ValueError('exact current valid pause required')
            _,api,_=native()
            with api.connect_closing() as conn:
                if not self.pause_status(conn)['drained']:raise ValueError('drained workers and effects required')
            path=self.root/'provider-policy.json'
            if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:
                raise ValueError('private provider policy required')
            before=Policy.parse(json.loads(path.read_bytes()))
            if before.project!=self.project.fingerprint():raise ValueError('provider project mismatch')
            after=Policy.parse({**before.values(),'enabled':False})
            write_json(path,after.values())
            return dict(policy_enabled=False,already_disabled=not before.enabled,
                relay_stop_or_recreate_required=True,pause_episode=episode,model_calls=0,
                counters_and_holds_untouched=True,delivery_approval=False)

    def configure_acceptance(self,expected_bundle):
        """Owner-approved F2/F3; never convert existing quality evidence."""
        with Owner(self.root),Journal(self.store.root/'effects').lock(['installation',self.project.fingerprint()]):
            path=self.root/'installation.json';before=json.loads(path.read_bytes())
            existing_upgrade=None
            if before.get('browser_contract')==2:
                for record_path in (self.store.root/'receipts').glob('*.json'):
                    record=self.store.receipt(record_path.stem)
                    if (record['kind']=='acceptance_upgrade' and record['payload']['after']==before
                            and record['payload']['before'].get('validation_bundle')==expected_bundle):
                        existing_upgrade=(record_path.stem,record)
                        graphs=(self.store.root/'releases').glob('*/graph.json')
                        if all(self.store.receipt(json.loads(p.read_bytes())['receipt'],kind='release_graph')['payload'].get('validation_bundle')
                               ==before['validation_bundle'] for p in graphs):
                            return dict(browser_contract=2,receipt=record_path.stem,already_installed=True,dispatch_started=False)
                        break
                if not existing_upgrade and before.get('validation_bundle')!=expected_bundle:
                    raise ValueError('installed acceptance bundle has no matching upgrade receipt')
            if not existing_upgrade and before.get('validation_bundle')!=expected_bundle:raise ValueError('exact previous validation bundle required')
            control=self.control.read()
            if not control['paused'] or control.get('error'):raise ValueError('valid explicit pause required')
            policy=self.root/'provider-policy.json'
            if not self.project.qualification and (not policy.is_file() or Policy.parse(json.loads(policy.read_bytes())).enabled):
                raise ValueError('disabled provider policy required')
            _,api,_=native()
            with api.connect_closing() as conn:
                if not self.pause_status(conn)['drained']:raise ValueError('drained workers and effects required')
                kinds={json.loads(row['body']).get('kind') for row in conn.execute('SELECT body FROM tasks').fetchall()}
                if before.get('browser_contract')!=2:
                    if not kinds<={'release','brief'}:
                        raise ValueError('initial acceptance upgrade is allowed only before planning and delivery')
                else:
                    # A planned but not yet validated increment may receive an
                    # additive representation repair. No baseline/Red/freeze or
                    # job (even an incomplete one) can be reinterpreted.
                    if not kinds<={'release','brief','plan','tests','implementation','integration'}:
                        raise ValueError('unsupported pre-quality board state')
                    allowed={'product_brief','brief_approval','product_answer','work_plan','plan_review',
                             'release_graph','release_seed','model_activity','activity_interrupted','acceptance_upgrade'}
                    if any(self.store.receipt(p.stem)['kind'] not in allowed
                           for p in (self.store.root/'receipts').glob('*.json')):
                        raise ValueError('existing quality or diagnostic evidence forbids acceptance repair')
                    jobs=self.store.root/'jobs'
                    if jobs.exists() and any(jobs.iterdir()):raise ValueError('existing validation job forbids acceptance repair')
            if not self.project.browser_tdd or not self.project.delivery_roles:
                raise ValueError('qualified browser TDD and delivery roles required')
            after=(existing_upgrade[1]['payload']['after'] if existing_upgrade else
                   {**before,'validation_bundle':seal_validation(self.store),'browser_contract':2})
            receipt=existing_upgrade[0] if existing_upgrade else self.store.record('acceptance_upgrade',dict(project=self.project.fingerprint(),actor='operator'),
                dict(before=before,after=after,pause_episode=control['episode'],
                    authority='Owner-approved audit 2026-10-27 F2/F3; business brief remains unchanged',
                    model_calls=0,delivery_approval=False))
            graphs=[]
            if any((self.store.root/'releases').glob('*/graph.json')):
                with api.connect_closing() as conn:graphs=self.releases.upgrade_unvalidated_graphs(conn,receipt)
            write_json(path,after)
            return dict(browser_contract=2,receipt=receipt,already_installed=bool(existing_upgrade),graphs=graphs,dispatch_started=False)

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
                if worker_alive(recorded_worker(conn,row)):
                    raise EffectBlocked('prior SDK worker still alive; preserve its sandbox')
                Sandbox.recover(self.project,self.store,identity).close()
            except (Pending,EffectBlocked,ValueError,subprocess.SubprocessError) as error:
                self.settlement[binding['task']]=dict(run=binding['number'],category=type(error).__name__)
                if task:raise
        return self.settlement

    def spawn(self,task,workspace,*,board=None):
        check_source()
        admission=self.check_admission()
        # Profile existence is checked freshly by the native dispatcher. The
        # cached doctor list is diagnostic, never a second per-profile guard.
        if not admission['ready']:
            from tools.process_registry import RestartSafeScopeUnavailable
            raise RestartSafeScopeUnavailable('runtime admission deferred; inspect doctor/status')
        state=profile_admission(self.project,self.root,getattr(task,'assignee',None))
        if not state['ready']:
            from tools.process_registry import RestartSafeScopeUnavailable
            raise RestartSafeScopeUnavailable('profile deferred: '+','.join(state['errors']))
        if json.loads(task.body).get('kind')!='integration':
            state=self.provider_status()
            if not state['ready']:
                from tools.process_registry import RestartSafeScopeUnavailable
                raise RestartSafeScopeUnavailable('provider deferred: '+state['reason'])
        if self.project.delivery_roles:
            try:self.releases.admit(task)
            except (ValueError,KeyError,TypeError,OSError):
                from tools.process_registry import RestartSafeScopeUnavailable
                raise RestartSafeScopeUnavailable('assigned release graph invalid; no model worker started') from None
        self.settle(task.id)
        with self.control.lock():
            try:self.control.ensure()
            except ActivityPaused:
                from tools.process_registry import RestartSafeScopeUnavailable
                raise RestartSafeScopeUnavailable('operational pause; no worker started') from None
            return self._spawn(task,workspace,board=board)

    def _spawn(self,task,workspace,*,board=None):
        folder=self.root/'runs'/str(task.current_run_id);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        env={key:os.environ[key] for key in ('PATH','PYTHONPATH','HERMES_HOME','HERMES_KANBAN_DB',
             'HERMES_KANBAN_BOARD','HERMES_DISABLE_LAZY_INSTALLS','PYTHONDONTWRITEBYTECODE',
             'PYTHONSAFEPATH','PYTHONNOUSERSITE','FABRIQUINHA_SOURCE_DIGEST') if key in os.environ}
        fd=os.open(folder/'worker.log',os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
        with os.fdopen(fd,'ab') as log:
            process=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','worker',
                '--root',str(self.root),'--upstream',str(self.upstream),
                '--task',task.id,'--run',str(task.current_run_id)],stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        self.children.append(process)
        return process.pid

    def check_admission(self,*,force=False):
        now=time.monotonic()
        if force or self.admission is None or now>=self._next_admission:
            self.admission=doctor(self.project,self.root,self.store)
            self._next_admission=now+15
        return self.admission

    def provider_status(self):
        """Metadata only; no credential load or inference. Integration needs no model."""
        try:
            route=model_route(self.project,self.root/'route.json')
            self.provider=dict(ready=True,model=route['model'],reason=None)
        except Held as error:self.provider=dict(ready=False,reason=error.code,status=error.status)
        except (ValueError,KeyError,TypeError,OSError):self.provider=dict(ready=False,reason='InvalidProviderConfiguration')
        return self.provider

    def costs(self):
        route=model_route(self.project,self.root/'route.json',require_ready=False)
        policy=Policy.parse(json.loads((self.root/'provider-policy.json').read_bytes()))
        value=inspect_usage(policy,route['base_url'].removesuffix('/v1'))
        for activity,data in value['activities'].items():
            try:
                record=self.store.receipt(activity,kind='model_activity')
                if record['payload']['project']!=self.project.fingerprint():raise ValueError('foreign activity')
                data['execution']=record['binding']
                data['validation_bundle']=record['payload'].get('validation_bundle')
            except (ValueError,OSError,TypeError,KeyError):data['execution']=None
        return {**value,'accounting_only':True,'policy_changed':False}

    def settle_provider(self,conn):
        """Verified-dead held runs use the pinned native infrastructure deferral.

        Reclaim/unblock reset budgets; this restores the original lane while
        preserving counters. Native spawn_failed/infrastructure also provides
        cooldown. The immutable receipt distinguishes partial SDK work from a
        preflight refusal; neither is a functional failure or completed delivery.
        """
        kb,_,dispatch=native();issues={}
        for path in (self.root/'runs').glob('*/provider-wait.json'):
            try:
                number=int(path.parent.name)
                row=conn.execute('SELECT * FROM task_runs WHERE id=?',(number,)).fetchone()
                if not row:raise ValueError('provider wait has no native run')
                if row['ended_at'] is not None:continue
                wait=self.store.receipt(json.loads(path.read_bytes())['receipt'],kind='provider_wait')
                binding=wait['binding'];run=self.board.current(row['task_id'],number)
                if wait['payload']['project']!=self.project.fingerprint() or run.binding()!=binding:
                    raise ValueError('provider wait belongs to a different assignment')
                if worker_alive(recorded_worker(conn,row)):continue
                self.outbox.enqueue('provider-wait:'+str(number),dict(text=self.project.namespace+': '+run.task+
                    ' @'+run.actor+' provider wait; phase and functional failure budget preserved. '+wait['payload']['reason']))
                dispatch._record_task_failure(conn,run.task,'provider deferred: '+wait['payload']['reason'],
                    outcome='spawn_failed',infrastructure=True,release_claim=True,end_run=True)
                self.settle(run.task,conn=conn)
            except (ValueError,KeyError,TypeError,OSError,EffectBlocked) as error:issues[path.parent.name]=type(error).__name__
        self.provider_issues=issues
        return issues

    def pause_status(self,conn):
        busy=[];open_runs=[]
        for row in conn.execute('SELECT * FROM task_runs').fetchall():
            if row['ended_at'] is None:open_runs.append(row['id'])
            event=conn.execute("SELECT 1 FROM task_events WHERE run_id=? AND kind IN ('spawned','worker_registered') LIMIT 1",(row['id'],)).fetchone()
            if row['ended_at'] is not None and not row['worker_pid'] and not event:continue
            try:
                if worker_alive(recorded_worker(conn,row)):busy.append(dict(task=row['task_id'],run=row['id'],state='alive'))
            except (ValueError,EffectBlocked):busy.append(dict(task=row['task_id'],run=row['id'],state='unverified'))
        pending=[]
        for path in (self.store.root/'effects').glob('*.json'):
            if json.loads(path.read_bytes()).get('state')!='done':pending.append(path.stem)
        unretired=[]
        for path in (self.store.root/'agents').glob('*/sandbox.json'):
            if not (path.parent/'retirement.json').exists():unretired.append(path.parent.name)
        stopped=not (busy or open_runs or unretired or self.settlement)
        return dict(agents_stopped=stopped,drained=stopped and not pending,busy=busy,open_runs=open_runs,
                    unretired_sandboxes=unretired,pending_effects=pending)

    def maintain_pause(self,conn):
        control=self.control.read()
        if not control['paused'] or control['error']:return
        kb,_,_=native()
        for row in conn.execute('SELECT * FROM task_runs WHERE ended_at IS NULL').fetchall():
            try:
                if worker_alive(recorded_worker(conn,row)):continue
            except (ValueError,EffectBlocked):continue
            current=kb.get_task(conn,row['task_id'])
            if current.status=='running' and current.current_run_id==row['id']:
                # Already dead: reclaim cannot release a second worker beside
                # it, preserves review phase and does not spend a retry.
                kb.reclaim_task(conn,current.id,reason='operator_pause:'+str(control['episode']))
        self.settle(conn=conn)

    def pause(self):
        control=self.control.pause();_,kbc,_=native()
        with kbc.connect_closing() as conn:
            self.maintain_pause(conn);status=self.pause_status(conn)
        self.outbox.enqueue('pause:'+control['episode'],{'text':self.project.namespace+': pause requested; draining current activities.'})
        return dict(control=control,**status,delivery_approval=False)

    def resume(self,episode):
        with self.control.lock():
            old=self.control.read()
            if old['error'] or not old['paused'] or old['episode']!=episode:raise ValueError('exact current pause episode required')
            _,kbc,_=native()
            with kbc.connect_closing() as conn:
                self.maintain_pause(conn);status=self.pause_status(conn)
            if not status['agents_stopped']:raise EffectBlocked('workers/claims/sandboxes not settled; pause remains active')
            if not self.check_admission(force=True)['ready']:raise EffectBlocked('runtime admission failed; pause remains active')
            model_route(self.project,self.root/'route.json')  # Not a release of the old paid-provider gate.
            control=self.control.resume(episode)
        self.outbox.enqueue('resume:'+episode,{'text':self.project.namespace+': dispatch resumed; delivery gates remain mandatory.'})
        return dict(control=control,pending_effects=status['pending_effects'],delivery_approval=False)

    def tick(self):
        check_source()
        self.children=[child for child in self.children if child.poll() is None]
        # A changed project file cannot silently grant a live service authority.
        if Project.parse(json.loads((self.root/'project.json').read_bytes())).fingerprint()!=self.project.fingerprint():
            raise ValueError('project changed while service was running')
        _,kbc,dispatch=native()
        with kbc.connect_closing() as conn:
            self.settle_provider(conn)
            if self.control.read()['paused']:
                self.maintain_pause(conn)
                return dispatch.DispatchResult()
            self.settle(conn=conn)
            try:
                self.intake.reconcile(conn);self.intake_issues={}
            except (ValueError,KeyError,TypeError,OSError) as error:
                self.intake_issues={'category':type(error).__name__}
            self.release_issues=self.releases.reconcile(conn,self.release_services)
            self.integration_issues=self.wake_integrations(conn)
            self.recovery_issues=self.recovery.reconcile(conn,self.settle)
            admission=self.check_admission()
            return dispatch.dispatch_once(conn,spawn_fn=self.spawn,max_spawn=self.project.max_workers if admission['ready'] else 0,
                max_in_progress=self.project.max_workers,max_in_progress_per_profile=1)

    def park_integration(self,run,*,now=None):
        if run.kind!='integration' or run.reviewing:
            raise ValueError('only integration implementation waits may use scheduled')
        self.board.ensure(run)
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            row=conn.execute('SELECT worker_pid,worker_started_at,claim_lock FROM task_runs WHERE id=? AND task_id=?',
                             (run.number,run.task)).fetchone()
            if not row or row['worker_pid']!=os.getpid() or not row['worker_started_at'] or not row['claim_lock']:
                raise ValueError('only the verified native integration worker may park its claim')
            receipt=self.store.record('integration_wait',run.binding(),dict(
                project=self.project.fingerprint(),wake_at=(time.time() if now is None else now)+15))
            if not kb.schedule_task(conn,run.task,reason=json.dumps({'integration_wait':receipt}),
                                    expected_run_id=run.number):
                raise ValueError('native integration wait refused')
        return dict(status='scheduled',wait=receipt,delivery_approval=False)

    def wake_integrations(self,conn,*,now=None):
        """Only our exact scheduled effect waits; no general auto-unblock policy."""
        kb,_,_=native();issues={};now=time.time() if now is None else now
        for task in conn.execute("SELECT id,body,assignee FROM tasks WHERE status='scheduled'").fetchall():
            try:
                row=conn.execute('SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(task['id'],)).fetchone()
                if not row or row['outcome']!='scheduled' or row['ended_at'] is None:continue
                event=conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='scheduled' ORDER BY id DESC LIMIT 1",
                                   (task['id'],row['id'])).fetchone()
                if not event:continue
                reason=json.loads(event[0]).get('reason')
                try:values=json.loads(reason) if isinstance(reason,str) else {}
                except ValueError:continue
                if not isinstance(values,dict) or set(values)!={'integration_wait'}:continue
                receipt=self.store.receipt(values['integration_wait'],kind='integration_wait')
                data,binding=receipt['payload'],receipt['binding'];body=json.loads(task['body'])
                if not all(isinstance(value,dict) for value in (data,binding,body)):
                    raise ValueError('structured integration wait required')
                if (data['project']!=self.project.fingerprint() or binding['task']!=task['id']
                        or binding['number']!=row['id'] or binding['actor']!=row['profile']
                        or binding['actor']!=task['assignee'] or binding['author']!=task['assignee']
                        or binding['kind']!='integration' or binding['reviewing'] is not False
                        or binding['contract']!=digest(body) or binding['release']!=body.get('release')
                        or body.get('version')!=1 or body.get('kind')!='integration'):
                    raise ValueError('integration wait contract or owner changed')
                if now<data['wake_at'] or worker_alive(recorded_worker(conn,row)):continue
                if not kb.unblock_task(conn,task['id']):raise ValueError('native integration wake refused')
            except (ValueError,KeyError,TypeError,OSError,EffectBlocked) as error:
                issues[task['id']]=type(error).__name__
        return issues

    def integration_services(self,run):
        # Real production transport only. Qualification fixtures replace this
        # factory in their own process; no test endpoint/config bypass is shipped.
        return Repository(self.project,self.store,assignee=run.actor),GitHub(self.project,run.actor)

    def release_services(self,actor,*,task=None):
        return Repository(self.project,self.store,assignee=actor),GitHub(self.project,actor)

    def integrate(self,run,quality):
        self.board.ensure(run)
        if run.kind!='integration':raise ValueError('native integration activity required')
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:task=kb.get_task(conn,run.task)
        expected=self.project.repository.removeprefix('https://github.com/')
        if task.completion_contract in (None,'local-only'):
            raise ValueError('native PR completion contract required')
        if task.completion_contract!=expected:
            GitHub(self.project,run.actor).url(task.completion_contract)  # exact previously bound PR only
        repo,github=self.integration_services(run)
        publication=Publication(self.project,self.store,self.board,repo,github,runner=quality.runner)
        deployment=Deployment(self.project,self.store,self.board,quality.runner)
        if run.reviewing:
            rollout=self.board.input(run,'rollout',review_handoff=True)
            artifact=self.store.receipt(self.store.receipt(rollout,kind='rollout')['payload']['candidate'],kind='artifact')['payload']
            integrated=artifact['integrated']
            published=self.store.receipt(self.store.receipt(integrated,kind='integrated')['payload']['publication'],kind='publication')['payload']
            if self.project.local_ci:
                publication.local_ci.existing(artifact['commit'],published['base_sha'],stage='integrated')
            publication.require_ci(github.accept(published['pr'],artifact['commit']),artifact['commit'],time.time())
            evidence=deployment.qa(run,rollout,repo)
            self.board.finish_review(run,'Independent deployed QA; release acceptance remains separate',
                dict(published_pr=published['pr'],integrated=integrated,release_evidence=evidence,
                     baseline=artifact['snapshot'],base_commit=artifact['commit']))
            return dict(status='qa_completed',release_evidence=evidence,delivery_approval=False)
        published=publication.publish(run,self.board.input(run,'delivery'))
        integrated=publication.validate_integrated(run,published,quality)
        previous=self.releases.rollback_artifact(run) if self.project.delivery_roles else None
        if previous is None:previous=deployment.artifact(run,integrated,repo,baseline=True)
        candidate=deployment.artifact(run,integrated,repo)
        rollout=deployment.rollout(run,candidate,previous,repo)
        self.board.review(run,'Independent deployed QA after rollback and restoration',
            dict(rollout=rollout,integrated=integrated,published_pr=self.store.receipt(published,kind='publication')['payload']['pr']))
        return dict(status='qa_requested',rollout=rollout,delivery_approval=False)

    def status(self):
        _,kbc,_=native()
        with kbc.connect_closing() as conn:
            cards=[dict(row) for row in conn.execute('SELECT id,title,status,assignee,current_run_id,last_heartbeat_at,created_at,body, '
                '(SELECT started_at FROM task_runs WHERE id=tasks.current_run_id) AS run_started_at, '
                '(SELECT MAX(created_at) FROM task_events WHERE task_id=tasks.id) AS last_event_at '
                'FROM tasks ORDER BY created_at')]
            for card in cards:
                raw=card.pop('body')
                try:
                    document=json.loads(raw or '{}');card['contract']=digest(document)
                    card['kind']=document.get('kind') if isinstance(document,dict) else None
                except ValueError:card['contract']=None;card['kind']=None
                try:card['last_validation']=validation_progress(card,self.store,self.project)
                except (ValueError,OSError):card['last_validation']={'error':'EvidenceUnavailable'}
                if card['status']=='review' and card['assignee']=='fabriquinha-ceo':
                    try:
                        pending=self.intake.pending(conn,card['id'])
                        card['business_input']={key:value for key,value in pending.items() if key!='document'} if pending else None
                    except (ValueError,KeyError,TypeError,OSError):card['business_input']={'error':'EvidenceUnavailable'}
            try:incidents=self.recovery.status(conn)
            except (ValueError,KeyError,TypeError,OSError) as error:
                incidents=[dict(source=None,state='evidence_unavailable',block_event=0,
                    owner=(self.project.technical_roles or {}).get('cto','techlead'),
                    next_action='Restore diagnostic evidence before interpreting recovery as successful: '+type(error).__name__,delivery_approval=False)]
            for card in cards:
                matching=[i for i in incidents if i['source']==card['id']]
                if matching:
                    incident=max(matching,key=lambda i:i['block_event'])
                    card.update(technical_owner=incident['owner'],next_action=incident['next_action'])
                    if incident.get('corrective_task'):card['corrective_task']=incident['corrective_task']
            control=self.control.read()
            if control['paused']:control={**control,**self.pause_status(conn)}
        return dict(namespace=self.project.namespace,cards=cards,settlement=self.settlement,recovery_issues=self.recovery_issues,
                    integration_issues=self.integration_issues,intake_issues=self.intake_issues,release_issues=self.release_issues,
                    control=control,admission=self.admission,
                    provider=self.provider_status(),provider_issues=self.provider_issues,
                    incidents=incidents,notifications=self.outbox.summary(),qualification=self.project.qualification,
                    profiles=profile_report(self.project,self.root),delivery_approval=False)

    def serve(self,stop,*,interval=15):
        # Keep WAL sidecars present across short native API connections. This
        # is a connection lifetime, not an open write txn or an error retry.
        _,kbc,_=native()
        with native_keepalive(self.root/'home/kanban.db',kbc) as keeper:
            return self._serve(stop,interval=interval)

    def _serve(self,stop,*,interval=15):
        if not 0.1<=interval<=60:raise ValueError('bounded dispatch interval required')
        if not self.control.read()['paused']:self.provider_status()
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
                    if not self.control.read()['paused']:alerts(self.outbox,self.status()['cards'],self.store,now=time.time())
                except Exception as error:
                    self.outbox.save(self.outbox.root/'error.json',dict(category=type(error).__name__,at=time.time()))
                write_json(self.root/'status.json',dict(dispatcher_pid=os.getpid(),dispatcher_state='running',observed_at=time.time(),board=self.status()))
                stop.wait(interval)
        finally:
            stop.set();sender.join(timeout=4)
            write_json(self.root/'status.json',dict(dispatcher_pid=os.getpid(),dispatcher_state='stopped',observed_at=time.time(),board=self.status()))
        # Do not terminate healthy detached workers on dispatcher shutdown.

    def worker(self,task,number):
        _,kbc,_=native()
        with kbc.connect_closing() as keeper:
            keeper.execute('SELECT id FROM tasks LIMIT 1').fetchone()
            return self._worker(task,number)

    def _worker(self,task,number):
        kb,kbc,dispatch=native();sandbox=None
        with kbc.connect_closing() as conn:
            if not dispatch.adopt_worker_pid(conn,task,number,os.getpid()):
                raise ValueError('native claim lost before worker startup')
            owner=conn.execute('SELECT worker_pid FROM task_runs WHERE id=? AND task_id=?',(number,task)).fetchone()
            if not owner or owner['worker_pid']!=os.getpid():
                raise ValueError('native run belongs to another worker process')
            prompt=kb.build_worker_context(conn,task)
        run=self.board.current(task,number);quality=None
        try:
            self.control.ensure()
            os.environ['HERMES_HOME']=str(self.root/'home/profiles'/run.actor)
            def profile_check():
                if not profile_admission(self.project,self.root,run.actor)['ready']:
                    raise Held('profile_configuration_unqualified')
            profile_check()  # Before validator/sandbox creation or any SDK client.
            runner=IntegrationRunner if run.kind=='integration' else Runner
            quality=Quality(self.project,self.store,runner(self.project,self.store),self.board)
            if self.project.delivery_roles and run.kind in ('tests','implementation','integration'):
                context=self.releases.prepare(run,quality)
                prompt+='\nController-approved package context:\n'+json.dumps(context)
            if run.kind=='integration':
                try:result=self.integrate(run,quality)
                except Pending:
                    if run.reviewing:raise  # never lose a review's phase through schedule_task
                    result=self.park_integration(run)
                write_json(self.root/'runs'/str(number)/'activity.json',dict(binding=run.binding(),result=result))
                return
            guidance=self.recovery.guidance(run)
            if guidance:quality.review_after=self.store.receipt(guidance[-1]['receipt'],kind='diagnostic_decision')['binding']['number']
            if guidance:prompt+='\nController-recorded diagnostic guidance:\n'+json.dumps(guidance_context(guidance))
            try:route=model_route(self.project,self.root/'route.json')
            except (ValueError,KeyError,TypeError,OSError):raise Held('provider_configuration_changed') from None
            def provider_check():
                try:check_source()
                except (ValueError,TypeError,OSError):raise Held('source_changed') from None
                profile_check()
                try:current=model_route(self.project,self.root/'route.json')
                except (ValueError,KeyError,TypeError,OSError):raise Held('provider_configuration_changed') from None
                if current!=route:raise Held('provider_route_changed')
            def guard():
                self.control.ensure();provider_check()
            self.board.guard=guard
            if run.kind=='implementation' and not run.reviewing:
                work=self.board.workspace(run);frozen=quality.freeze(run,self.board.input(run,'tests'))
                if not any(work.iterdir()):self.store.checkout(frozen['snapshot'],work)
                else:quality.protect(frozen['snapshot'],self.store.capture(work),exact_tests=True)
            sandbox=(DraftActivity if run.kind in ('brief','plan') else Sandbox)(self.project,self.store,self.board,run)
            prompt='Delivery activity '+json.dumps(run.binding(),sort_keys=True)+'\n'+prompt
            policy=self.root/'provider-policy.json'
            output_limit=Policy.parse(json.loads(policy.read_bytes())).max_output_tokens if policy.exists() else None
            result=run_activity(sandbox,quality,route,prompt,stop_requested=lambda:self.control.read()['paused'],provider_check=provider_check,
                output_limit=output_limit,recovery_epoch=guidance[-1]['receipt'] if guidance else None)
            write_json(self.root/'runs'/str(number)/'activity.json',dict(binding=run.binding(),result=result))
        except Held as error:
            wait=self.store.record('provider_wait',run.binding(),dict(project=self.project.fingerprint(),
                reason=error.code,status=error.status,delivery_approval=False))
            write_json(self.root/'runs'/str(number)/'provider-wait.json',dict(receipt=wait))
        except ActivityPaused:
            interrupted=self.store.record('activity_interrupted',run.binding(),dict(project=self.project.fingerprint(),
                pause=self.control.read()['episode'],delivery_approval=False))
            write_json(self.root/'runs'/str(number)/'activity.json',dict(binding=run.binding(),interrupted=interrupted))
            # Keep claim until this process is really gone. Paused maintenance
            # then reclaims it natively, without changing author/review phase.
        except BaseException as error:
            control_refusal=getattr(quality,'control_refusal',None)
            suite_refusal=getattr(quality,'suite_refusal',None)
            browser_refusal=getattr(error,'browser_job',None)
            failure=self.store.record('worker_failure',run.binding(),dict(project=self.project.fingerprint(),
                category=type(error).__name__,message=str(error)[:2000],
                **({'control_refusal':control_refusal} if control_refusal else {}),
                **({'suite_refusal':suite_refusal} if suite_refusal else {}),
                **({'browser_refusal':browser_refusal} if browser_refusal else {})))
            with kbc.connect_closing() as conn:
                kb.block_task(conn,task,reason=json.dumps(dict(category=type(error).__name__,failure=failure)),
                              kind='capability',expected_run_id=number)
            raise
        finally:
            if sandbox:sandbox.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('serve','worker','status','doctor','pause','resume','costs','configure-acceptance','disable-provider'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--task');parser.add_argument('--run',type=int);parser.add_argument('--interval',type=float,default=15)
    parser.add_argument('--expect-pause')
    parser.add_argument('--expect-validation')
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
    else:
        runtime=Runtime(args.root,args.upstream)
        value=(runtime.disable_provider(args.expect_pause) if args.operation=='disable-provider' else
               runtime.configure_acceptance(args.expect_validation) if args.operation=='configure-acceptance' else
               runtime.pause() if args.operation=='pause' else runtime.resume(args.expect_pause)
               if args.operation=='resume' else runtime.check_admission(force=True)
               if args.operation=='doctor' else runtime.costs() if args.operation=='costs' else runtime.status())
        print(json.dumps(value,indent=2))


if __name__=='__main__':main()
