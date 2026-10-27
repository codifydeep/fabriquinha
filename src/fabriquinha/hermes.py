"""Native Hermes tools attached to a controller-owned sandbox, no SDK/loop patch.

One worker process per claim. Never install the registry policy in a shared
gateway process. The controller owns Docker lifecycle; the backend only execs.
"""
from functools import wraps
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import urlsplit
from .artifacts import digest
from .effects import Journal, EffectBlocked, write_json
from .executor import docker, grouping, phase_mounts,validation_files
from .provider import OUTPUT_LIMITS


# Runs inside the existing lease, not on the host. A Linux subreaper owns only
# this command's descendants, including detached browser/server processes.
EXEC_GUARD = '''import ctypes, os, signal, subprocess, sys, time
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(36, 1, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), 'subreaper unavailable')
interrupted = [False]
def interrupt(*args): interrupted[0] = True
signal.signal(signal.SIGTERM, interrupt)
signal.signal(signal.SIGINT, interrupt)
process = subprocess.Popen(sys.argv[2:], start_new_session=True)
deadline = time.monotonic() + float(sys.argv[1])
while process.poll() is None and not interrupted[0] and time.monotonic() < deadline:
    time.sleep(.02)
code = process.poll()
if code is None: code = 130 if interrupted[0] else 124
def children():
    with open('/proc/self/task/' + str(os.getpid()) + '/children') as stream:
        return [int(pid) for pid in stream.read().split()]
def reap():
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0: break
        except ChildProcessError: break
def stop_children(sig):
    # Unreaped direct children cannot have their PIDs recycled. No host PID,
    # sibling exec, global process scan or process-group guess is signalled.
    for pid in children():
        try: os.kill(pid, sig)
        except ProcessLookupError: pass
leftovers = bool(children())
for sig, grace in ((signal.SIGTERM, 2), (signal.SIGKILL, 5)):
    until = time.monotonic() + grace
    while children() and time.monotonic() < until:
        stop_children(sig)
        reap()
        time.sleep(.02)
    reap()
if children():
    print('[Sandbox could not reap command descendants]', file=sys.stderr)
    sys.exit(125)
if code == 124: print('[Sandbox command deadline exceeded]', file=sys.stderr)
elif leftovers: print('[Sandbox command descendants retired]', file=sys.stderr)
sys.exit(code if code >= 0 else 128 - code)
'''


def bounded_exec(cid,argv,timeout,*,stdin=False):
    """The deadline must survive loss of the host's docker-exec client."""
    if (not isinstance(cid,str) or not re.fullmatch('[a-f0-9]{64}',cid)
            or not isinstance(argv,(list,tuple)) or not argv or any(not isinstance(a,str) for a in argv)
            or type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0):
        raise ValueError('exact sandbox, argv and finite positive deadline required')
    return ['docker','exec',*(['-i'] if stdin else []),cid,'python','-B','-c',EXEC_GUARD,
            format(min(timeout,120),'g'),*argv]


def activity_anchor(project,run,route,recovery_epoch=None):
    identity=dict(project=project.fingerprint(),subject=run.subject(),model=route['model'],
                  provider=route['provider'],api_mode=route['api_mode'])
    if recovery_epoch is not None:
        if not isinstance(recovery_epoch,str) or not re.fullmatch('[a-f0-9]{64}',recovery_epoch):
            raise ValueError('controller-validated diagnostic receipt required for context refresh')
        identity['recovery_epoch']=recovery_epoch
    return 'fabriquinha-'+digest(identity)[:32]


def sandbox_context(prompt):
    """Native workspace paths describe the controller, not the tool filesystem."""
    return '\n'.join('Workspace: dir @ /workspace (isolated tool filesystem; host paths are unavailable)'
        if line.startswith('Workspace: ') else line for line in prompt.splitlines())


def terminal_arguments(args,limit):
    """Exploration is bounded; qualification remains the fixed delivery gate."""
    if not isinstance(args,dict):raise ValueError('terminal arguments must be an object')
    timeout=args.get('timeout')
    if timeout is not None and (type(timeout) is not int or not 1<=timeout<=limit):
        raise ValueError('terminal timeout must be at most '+str(limit)+' seconds. Split exploratory batches; use delivery_submit for complete qualification, never replace it with partial test runs.')
    return {**args,'timeout':limit if timeout is None else timeout}


def terminal_schema(limit):
    """Scope native metadata before the SDK takes its tool-schema snapshot."""
    import tools.terminal_tool  # Register through the native extension API.
    from tools.registry import registry
    entry=next(e for e in registry.get_all_entries() if e.name=='terminal')
    fields={name:getattr(entry,name) for name in entry.__dataclass_fields__}
    schema=json.loads(json.dumps(entry.schema))
    schema['parameters']['properties']['timeout'].update(minimum=1,maximum=limit,default=limit,
        description='Controller exploration limit in seconds; at most '+str(limit)+'. Use fixed delivery_submit for qualification.')
    fields['schema']=schema
    registry.register(**fields,override=True)


def incomplete_activity(result, output_limit):
    """Retain actionable SDK state without copying response text or credentials."""
    result=result if isinstance(result,dict) else {}
    error=result.get('error')
    code=('output_budget_exceeds_policy' if isinstance(error,str) and 'output_budget_exceeds_policy' in error else
          'sdk_failed' if result.get('failed') is True else 'missing_terminal_operation')
    state=dict(code=code,output_limit=output_limit,failed=result.get('failed') is True)
    calls=result.get('api_calls')
    if type(calls) is int and 0<=calls<=1000:state['api_calls']=calls
    return ValueError('activity ended without a controller-validated native handoff; SDK status '+json.dumps(state))


def command(project, expected):
    return ['create','--name',project.namespace+'-agent-'+digest(expected)[:16],
        *grouping('agent',project.namespace),'--label','fabriquinha.agent='+digest(expected),
        '--label','fabriquinha.task='+expected['binding']['task'],
        '--network','none','--read-only','--user','65534:65534','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--memory','512m','--cpus','1',
        '--pids-limit','128','--tmpfs','/tmp:rw,noexec,nosuid,size=128m',
        '--log-opt','max-size=1m','--log-opt','max-file=2','--workdir','/workspace',
        '--env','HOME=/tmp',*phase_mounts(expected['workspace'],project.tests_dir,expected['phase'],
                                      baseline_tests=expected['baseline_tests']),
        '--entrypoint','/bin/sh',project.validation_image,'-c','exec sleep infinity']


class Sandbox:
    def __init__(self,project,store,board,run):
        board.ensure(run)
        if run.kind not in ('tests','implementation','diagnostic'):
            raise ValueError('author or review phase required')
        self.project,self.store,self.board,self.run=project,store,board,run
        self.phase='review' if run.reviewing or run.kind=='diagnostic' else run.kind
        baseline=[]
        if run.kind=='diagnostic':
            record=store.receipt(board.input(run,'incident'),kind='incident')
            if record['payload']['project']!=project.fingerprint() or record['binding']['release']!=run.release:
                raise ValueError('diagnostic belongs to another project or release')
            self.workspace=store.tree(record['payload']['snapshot'])
        elif run.reviewing:
            kind='red' if run.kind=='tests' else 'green'
            key=board.input(run,kind,review_handoff=True)
            if kind=='red':
                from .quality import Quality
                record=Quality(project,store,None,board).test_evidence(key)
            else:record=store.receipt(key,kind='green')
            binding=record['binding']
            if (binding['task']!=run.task or binding['contract']!=run.contract
                    or binding['release']!=run.release or binding['actor']!=run.author
                    or record['payload']['project']!=project.fingerprint()):
                raise ValueError('exact current immutable review handoff required')
            self.workspace=store.tree(record['payload']['snapshot'])
        else:
            self.workspace=board.workspace(run).resolve()
            if run.kind=='tests':
                baseline=[p for p in store.manifest(board.input(run,'baseline'))
                          if p.startswith(project.tests_dir+'/')]
                from .repairs import repair_authority
                authority=repair_authority(project,store,board,run)
                if authority and authority['proposal']['classification']=='test_contract':
                    baseline=[p for p in baseline if p not in authority['proposal']['test_paths']]
        if ',' in str(self.workspace):raise ValueError('Docker bind source cannot contain a comma')
        self.expected=dict(binding=run.binding(),project=project.fingerprint(),
            workspace=str(self.workspace),phase=self.phase,baseline_tests=baseline,image=project.validation_image)
        self.key=digest(self.expected)
        self.folder=store.root/'agents'/self.key
        self.journal=Journal(store.root/'effects')
        self.cid=None;self.closed=False;self.closing=False

    @classmethod
    def recover(cls,project,store,expected):
        """Retirement only, from a trusted private create intent, never a worker argument.

        The runtime must first prove the native worker is dead. No new tool
        authority is granted by reconstructing an old lease.
        """
        from .board import Run
        if (not isinstance(expected,dict) or set(expected)!={'binding','project','workspace','phase','baseline_tests','image'}
                or expected['project']!=project.fingerprint() or expected['image']!=project.validation_image):
            raise ValueError('exact controller-owned sandbox intent required')
        run=Run(**expected['binding'])
        phase='review' if run.reviewing or run.kind=='diagnostic' else run.kind
        if (run.kind not in ('tests','implementation','diagnostic') or expected['phase']!=phase
                or not Path(expected['workspace']).is_absolute()):
            raise ValueError('known sandbox phase and absolute workspace required')
        sandbox=cls.__new__(cls)
        sandbox.project,sandbox.store,sandbox.board,sandbox.run=project,store,None,run
        sandbox.expected,sandbox.phase,sandbox.workspace=expected,phase,Path(expected['workspace'])
        sandbox.key=digest(expected);sandbox.folder=store.root/'agents'/sandbox.key
        sandbox.journal=Journal(store.root/'effects')
        sandbox.cid=None;sandbox.closed=False;sandbox.closing=True
        return sandbox

    def ensure(self):
        if self.closed or self.closing:raise ValueError('sandbox lease closed')
        self.board.ensure(self.run)
        if not self.run.reviewing and self.run.kind!='diagnostic' and self.board.workspace(self.run)!=self.workspace:
            raise ValueError('assigned workspace changed')
        if self.cid and not self.inspect(self.cid)['State']['Running']:
            raise EffectBlocked('owned sandbox stopped; controller diagnosis required')

    def inspect(self,container):
        info=json.loads(docker('inspect',container))[0]
        cfg,host=info['Config'],info['HostConfig']
        args=command(self.project,self.expected)
        expected={}
        for index,value in enumerate(args):
            if value=='--mount':
                fields=dict(part.split('=',1) if '=' in part else (part,'') for part in args[index+1].split(','))
                expected[fields['dst']]=(str(Path(fields['src']).resolve()),'readonly' not in fields)
        binds={m['Destination']:(str(Path(m['Source']).resolve()),m['RW'])
               for m in info.get('Mounts',[]) if m['Type']!='tmpfs'}
        labels=cfg.get('Labels',{})
        if (info['Image']!=self.project.validation_image or labels.get('fabriquinha.agent')!=self.key
                or labels.get('com.docker.compose.project')!=self.project.namespace+'-tests'
                or cfg.get('User')!='65534:65534' or cfg.get('Entrypoint')!=['/bin/sh']
                or host.get('NetworkMode')!='none' or host.get('Privileged') or not host.get('ReadonlyRootfs')
                or host.get('CapAdd') or 'ALL' not in (host.get('CapDrop') or []) or binds!=expected
                or any(e.split('=',1)[0] in {'GH_TOKEN','GITHUB_TOKEN','OPENROUTER_API_KEY'} for e in cfg.get('Env',[]))):
            raise EffectBlocked('native tools sandbox identity rejected')
        return info

    def _created(self):
        args=command(self.project,self.expected);name=args[args.index('--name')+1]
        try:return {'container':self.inspect(name)['Id']}
        except subprocess.CalledProcessError as error:
            if 'No such' in (error.stderr or ''):return None
            raise

    def start(self):
        self.ensure()
        args=command(self.project,self.expected)
        self.cid=self.journal.do(self.key+':agent-create',self.expected,
            lambda:({'container':docker(*args).strip()}),self._created)['container']
        if not re.fullmatch('[a-f0-9]{64}',self.cid):
            raise EffectBlocked('exact Docker container identity required')
        self.board.ensure(self.run)
        def running():
            return {'running':True} if self.inspect(self.cid)['State']['Running'] else None
        def start():
            self.inspect(self.cid);docker('start',self.cid)
            return running()
        self.journal.do(self.key+':agent-start',self.expected,start,running)
        info=self.inspect(self.cid)
        write_json(self.folder/'sandbox.json',dict(identity=self.expected,container=self.cid,
            mounts=info['Mounts'],state=info['State'],image=info['Image']))

    def close(self):
        """Only this owned lease; archive before exact-ID stop/removal, no force."""
        self.closing=True
        if not self.cid and (self.journal.root/(digest(self.key+':agent-create')+'.json')).exists():
            def never_create():raise EffectBlocked('retirement may observe creation, never issue it')
            self.cid=self.journal.do(self.key+':agent-create',self.expected,never_create,self._created)['container']
        if self.cid and not self.closed:
            def exists():return self.cid in docker('ps','-aq','--no-trunc','--filter','id='+self.cid).split()
            if exists():
                info=self.inspect(self.cid)
                write_json(self.folder/'before-retirement.json',dict(container=self.cid,image=info['Image'],
                    state=info['State'],mounts=info['Mounts'],labels=info['Config']['Labels']))
                write_json(self.folder/'logs.json',dict(output=docker('logs',self.cid)[:1024*1024]))
            def stopped():
                return {'stopped':True} if not exists() or not self.inspect(self.cid)['State']['Running'] else None
            def stop():
                if self.inspect(self.cid)['State']['Running']:docker('stop','--time','1',self.cid)
                return stopped()
            self.journal.do(self.key+':agent-stop',self.expected,stop,stopped)
            def removed():return {'retired':True} if not exists() else None
            def remove():
                info=self.inspect(self.cid)
                if info['State']['Running']:raise EffectBlocked('sandbox still running before removal')
                docker('rm',self.cid)
                return removed()
            self.journal.do(self.key+':agent-remove',self.expected,remove,removed)
            write_json(self.folder/'retirement.json',dict(container=self.cid,retired=True,volumes_removed=0))
        self.closed=True


def install_backend(sandbox):
    """Use the native pluggable backend ABC; never replace a built-in backend."""
    from agent.terminal_env_provider import TerminalEnvironmentProvider
    from agent.terminal_env_registry import register_provider
    from tools.environments.base import BaseEnvironment
    from tools.environments.base_output import _popen_bash
    from tools.environments.remote_common import bash_argv

    class AttachedEnvironment(BaseEnvironment):
        def __init__(self,timeout):
            sandbox.start()
            super().__init__('/workspace',min(timeout,120))
            self.init_session()

        def _run_bash(self,text,*,login=False,timeout=120,stdin_data=None):
            sandbox.ensure()
            return _popen_bash(bounded_exec(sandbox.cid,bash_argv(text,login),timeout,stdin=stdin_data is not None),
                               stdin_data,start_new_session=True)

        def cleanup(self):
            # Native cache eviction must not delete a controller-owned lease.
            # The worker's finally block calls Sandbox.close(), including on error.
            return None

    class Provider(TerminalEnvironmentProvider):
        name='fabriquinha'
        def is_available(self):return not sandbox.closed and not sandbox.closing
        def create_environment(self,*,timeout,**kwargs):return AttachedEnvironment(timeout)

    register_provider(Provider())
    os.environ.update(TERMINAL_ENV='fabriquinha',TERMINAL_CWD='/workspace')


def tool_names(sandbox):
    if sandbox.run.kind in ('brief','plan'):return set()
    names={'read_file','search_files'}
    if not sandbox.run.reviewing and sandbox.run.kind!='diagnostic':names.update({'write_file','patch','terminal','process_manage'})
    return names


def restrict_handlers(sandbox,allowed):
    """Prune registry handlers too, not just advertised schemas, in this worker.

    Called after AIAgent construction and before its first turn. Only a dedicated
    single-claim worker process may use this policy; never a multiplexed gateway.
    """
    from tools.registry import registry
    for entry in registry.get_all_entries():
        if entry.name not in allowed:
            registry.deregister(entry.name)
            continue
        def guard(handler,entry_name):
            @wraps(handler)
            def guarded(*args,**kwargs):
                if entry_name in {'delivery_submit','delivery_review','diagnostic_validate','diagnostic_decide'}:sandbox.board.ensure(sandbox.run)
                else:sandbox.ensure()
                if entry_name=='terminal':
                    if len(args)!=1:raise ValueError('one terminal argument object required')
                    args=(terminal_arguments(args[0],min(120,sandbox.project.timeout_seconds)),)
                return handler(*args,**kwargs)
            return guarded
        fields={name:getattr(entry,name) for name in entry.__dataclass_fields__}
        fields['handler']=guard(entry.handler,entry.name)
        registry.register(**fields,override=True)


def register_delivery_tools(sandbox,quality,*,on_terminal=None):
    if sandbox.run.kind in ('brief','plan'):
        from .intake import register_draft
        return register_draft(sandbox,on_terminal)
    if sandbox.run.kind=='diagnostic':
        from .recovery import register_diagnostic
        return register_diagnostic(sandbox,quality,on_terminal)
    from .quality import DeliveryTools
    from tools.registry import registry
    operations=DeliveryTools(sandbox,quality)
    if sandbox.run.reviewing:
        from .quality import REVIEW_FINDINGS_CONTRACT,CONTROL_REVIEW_CONTRACT
        name='delivery_review'
        schema=dict(type='object',additionalProperties=False,required=['decision','reason','findings'],properties=dict(
            decision={'type':'string','enum':['approve','changes','escalate'],'description':REVIEW_FINDINGS_CONTRACT},reason={'type':'string','minLength':1,'maxLength':2000},
            findings=dict(type='array',maxItems=8,description=REVIEW_FINDINGS_CONTRACT,items=dict(type='object',additionalProperties=False,
                required=['path','line','detail'],properties=dict(path={'type':'string'},
                    line={'type':'integer','minimum':1},detail={'type':'string','minLength':1,'maxLength':2000})))))
        if sandbox.run.kind=='tests':
            schema['properties']['control_risks']=dict(type='array',maxItems=32,description=CONTROL_REVIEW_CONTRACT,
                items=dict(type='object',additionalProperties=False,required=['case','reason'],properties=dict(
                    case=dict(type='string',minLength=1,maxLength=1024),reason=dict(type='string',minLength=1,maxLength=2000))))
        operation=operations.review
        description=('Review the immutable delivery: approve, request concrete changes, or escalate a technical impasse to CTO. '
            'Use escalate instead of repeatedly requesting unsupported work or ending in prose. It never approves delivery. '
            'Never recreate Red or edit author work.')
        if sandbox.run.kind=='tests':description+=' '+CONTROL_REVIEW_CONTRACT
    else:
        name='delivery_submit'
        schema=dict(type='object',additionalProperties=False,properties={})
        if sandbox.run.kind=='implementation':
            schema.update(required=['mutations'],properties=dict(mutations=dict(type='array',minItems=1,maxItems=8,
                items=dict(type='object',minProperties=1,maxProperties=16,
                           additionalProperties=dict(type='string',maxLength=131072)))))
        operation=operations.submit
        description=('Validate the actual workspace and request independent review. '
            'Tests phase: real Red. Implementation: Green and behavior-changing product mutations. '
            'On validation error correct the work; never remove or weaken tests. No pass flags, commands or receipt IDs accepted.')
    def handler(args,**kwargs):
        result=operation(args)
        if on_terminal:on_terminal(result)
        return json.dumps(result)
    registry.register(name=name,toolset='fabriquinha_delivery',
        schema=dict(name=name,description=description,parameters=schema),handler=handler)
    return {name},operations


def activity_route(route,activity):
    """Scope inherited SDK clients at the existing relay, not SDK internals.

    Keep the persisted route/session anchor stable. Auxiliary clients inherit
    this address even when they do not copy main-call request headers.
    """
    url=urlsplit(route['base_url'])
    if (not re.fullmatch('[a-f0-9]{64}',str(activity)) or url.scheme!='http' or url.hostname!='127.0.0.1'
            or not url.port or url.username or url.password or url.path!='/v1' or url.query or url.fragment):
        raise ValueError('fixed loopback relay and exact activity identity required')
    return {**route,'base_url':url._replace(path='/activities/'+activity+'/v1').geturl()}


def run_activity(sandbox,quality,route,prompt,*,run_seconds=600,stop_requested=None,provider_check=None,output_limit=None,recovery_epoch=None):
    """Trusted SDK adapter; no lifecycle inference from the assistant's prose.

    Route comes from controller configuration, not a model tool argument.
    Qualification is loopback-only. Production provider release remains a
    separate installation/authorization step; no fallback route is configured.
    """
    if (not isinstance(route,dict) or set(route)!={'base_url','api_key','provider','api_mode','model'}
            or any(not isinstance(v,str) or not v for v in route.values())
            or type(run_seconds) is not int or not 1<=run_seconds<=3600
            or output_limit is not None and (type(output_limit) is not int or output_limit not in OUTPUT_LIMITS)):
        raise ValueError('explicit bounded controller model route required')
    url=urlsplit(route['base_url'])
    if url.username or url.password or sandbox.project.qualification and (url.scheme!='http' or url.hostname!='127.0.0.1'):
        raise ValueError('qualification model route must be loopback only')
    from hermes_cli.profiles import get_active_profile_name
    if get_active_profile_name()!=sandbox.run.actor:raise ValueError('worker must bind the assigned profile')
    if sandbox.run.kind not in ('brief','plan'):install_backend(sandbox)
    from run_agent import AIAgent
    from hermes_state import SessionDB
    from toolsets import create_custom_toolset
    db=SessionDB();agent=None;terminal={};watcher=None;watch_done=threading.Event();provider_hold=[]
    def finished(result):
        terminal.update(result)
        agent.interrupt(tool_reason='delivery_handoff')
    gates,operations=register_delivery_tools(sandbox,quality,on_terminal=finished)
    allowed=tool_names(sandbox)|gates
    create_custom_toolset('fabriquinha_activity','Controller-selected delivery activity',tools=sorted(allowed))
    anchor=activity_anchor(sandbox.project,sandbox.run,route,recovery_epoch)
    session=db.resolve_resume_session_id(anchor);previous=db.get_session(session)
    try:
        history=None
        if previous:
            if previous['profile_name']!=sandbox.run.actor:raise ValueError('session belongs to another profile')
            db.assert_resume_safe(session);history,_=db.get_resume_conversations(session)
        phase=('Refine the original objective into a verifiable product brief. Use brief_question only for essential user/business decisions, '
               'not architecture or tools. Preserve all stated scope; do not ask the CEO to repeat supplied information. '
               'Use brief_submit when ready for explicit CEO approval. This is not delivery or budget approval.'
               if sandbox.run.kind=='brief' else
               'Review the exact work plan against the approved brief and submit plan_review: approve or concrete changes. '
               'Do not rewrite the plan or implement the product.' if sandbox.run.kind=='plan' and sandbox.run.reviewing else
               'Create the technical work DAG from the approved brief using plan_submit. Cover every acceptance criterion. '
               'Own technical choices; invoke CTO expertise through independent plan review, not the CEO. '
               'Specify outcomes, owners and dependencies, not prewritten code or fabricated TDD evidence.' if sandbox.run.kind=='plan' else
               'Diagnose the recorded technical incident. Read immutable evidence; run diagnostic_validate for a real SPIKE. '
               'Use diagnostic_decide with concrete findings: lead may escalate to CTO; resume needs a real experiment. '
               'Previous diagnoses are historical evidence, not inherited orders. Reassess current observations; a past hold does not require another hold when verified conditions changed. '
               'Diagnostic failures/errors are observations, never delivery approval. Follow phase_expectation: a tests author needs valid Red, not Green; return test errors to that author. '
               'Escalate an inconclusive technical diagnosis to CTO rather than demanding implementation before test freeze. '
               'Follow allowed_actions; preserve triage and expired effects, holding with a concrete repair action when resume is unavailable. '
               'Never edit the author, approve delivery, bypass tests or send technical choices to the CEO.'
               if sandbox.run.kind=='diagnostic' else 'Review existing immutable delivery; never write or recreate Red. Submit findings using delivery_review.'
               if sandbox.run.reviewing else 'Implement the current phase with real tests and use delivery_submit. '
               'Validation errors require correction, not weakening tests. Do not claim completion in prose.')
        phase+=' File tools see only /workspace; controller host paths are unavailable. Use small complete tool calls within the fixed output budget, not one oversized command or file batch. Exploratory terminal calls are limited to '+str(min(120,sandbox.project.timeout_seconds))+' seconds. The delivery_submit gate runs the full suite; partial exploratory runs never qualify delivery. Use its covered/missing control feedback rather than repeating unchanged mutation proposals.'
        if getattr(operations,'repair',False) is True:
            phase=('Independently review the exact corrective classification, brief authority and explicit QA paths; use plan_review.'
                   if sandbox.run.reviewing else
                   'Classify the recorded deployed QA failure against the approved brief using repair_submit. Propose product or test_contract with evidence and explicit existing QA paths. No new brief, whole-release plan, implementation or fabricated evidence.')
        prompt=sandbox_context(prompt)
        if 'terminal' in allowed:terminal_schema(min(120,sandbox.project.timeout_seconds))
        bundle=validation_files(sandbox.project,sandbox.store)[0]
        activity=sandbox.store.record('model_activity',sandbox.run.binding(),{'project':sandbox.project.fingerprint(),
            **({'validation_bundle':bundle} if bundle else {})})
        agent=AIAgent(**activity_route(route,activity),max_tokens=output_limit,max_iterations=40,enabled_toolsets=['fabriquinha_activity'],disabled_toolsets=['kanban'],
            request_overrides={'extra_headers':{'X-Fabriquinha-Activity':activity}},
            quiet_mode=True,skip_context_files=True,skip_memory=True,skip_background_review=True,
            session_db=db,session_id=session,cwd='/workspace',run_budget_seconds=run_seconds,
            fallback_model=None,ephemeral_system_prompt=phase)
        if agent.valid_tool_names!=allowed:raise ValueError('native tool surface diverged from phase policy')
        restrict_handlers(sandbox,allowed)
        if sandbox.run.kind in ('tests','implementation'):
            prompt+='\nController-recorded previous review findings:\n'+json.dumps(sandbox.board.review_feedback(sandbox.run,sandbox.store))
        if sandbox.run.reviewing or sandbox.run.kind in ('diagnostic','brief','plan'):
            label=('Approved business context' if sandbox.run.kind in ('brief','plan') else
                   'Incident context' if sandbox.run.kind=='diagnostic' else 'TDD evidence (historical Red is not to be reproduced)')
            prompt+='\nController-recorded '+label+':\n'+json.dumps(operations.evidence())
        if stop_requested or provider_check:
            sandbox.board.ensure(sandbox.run)
            def watch():
                while not watch_done.is_set():
                    if provider_check and not terminal:
                        from .provider import Held
                        try:provider_check()
                        except Held as error:
                            provider_hold.append(error)
                            if not watch_done.is_set() and not agent.is_interrupted:agent.hard_interrupt(tool_reason='provider_wait')
                            return
                    if stop_requested and stop_requested() and not terminal and not agent.is_interrupted:
                        agent.hard_interrupt(tool_reason='operator_pause')
                    watch_done.wait(0.25)
            watcher=threading.Thread(target=watch,daemon=True);watcher.start()
        try:
            result=agent.run_conversation(prompt,conversation_history=history,
                                         system_message=previous.get('system_prompt') if previous else None)
        except Exception:
            if not terminal and provider_check:provider_check()
            raise
        if not terminal and provider_hold:raise provider_hold[0]
        if not terminal and provider_check:provider_check()
        if not terminal and stop_requested and stop_requested():
            from .operations import ActivityPaused
            raise ActivityPaused('SDK activity interrupted by operational pause')
        if not terminal:raise incomplete_activity(result,output_limit)
        return dict(transition=terminal,session=agent.session_id,resumed=bool(previous),recovery_epoch=recovery_epoch,
                    sdk_exit=result.get('turn_exit_reason',result.get('exit_reason')),delivery_approval=False)
    finally:
        watch_done.set()
        if watcher:watcher.join(timeout=4)
        if agent:agent.close()
        db.close();sandbox.close()
