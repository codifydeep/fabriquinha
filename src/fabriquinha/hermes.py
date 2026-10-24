"""Native Hermes tools attached to a controller-owned sandbox, no SDK/loop patch.

One worker process per claim. Never install the registry policy in a shared
gateway process. The controller owns Docker lifecycle; the backend only execs.
"""
from functools import wraps
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from .artifacts import digest
from .effects import Journal, EffectBlocked, write_json
from .executor import docker, grouping, phase_mounts


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
        if run.kind not in ('tests','implementation'):
            raise ValueError('author or review phase required')
        self.project,self.store,self.board,self.run=project,store,board,run
        self.phase='review' if run.reviewing else run.kind
        baseline=[]
        if run.reviewing:
            kind='red' if run.kind=='tests' else 'green'
            record=store.receipt(board.input(run,kind,review_handoff=True),kind=kind)
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
        phase='review' if run.reviewing else run.kind
        if (run.kind not in ('tests','implementation') or expected['phase']!=phase
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
        if not self.run.reviewing and self.board.workspace(self.run)!=self.workspace:
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
            return _popen_bash(['docker','exec',*(['-i'] if stdin_data is not None else []),
                sandbox.cid,*bash_argv(text,login)],stdin_data,start_new_session=True)

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
    names={'read_file','search_files'}
    if not sandbox.run.reviewing:names.update({'write_file','patch','terminal','process_manage'})
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
                if entry_name in {'delivery_submit','delivery_review'}:sandbox.board.ensure(sandbox.run)
                else:sandbox.ensure()
                return handler(*args,**kwargs)
            return guarded
        fields={name:getattr(entry,name) for name in entry.__dataclass_fields__}
        fields['handler']=guard(entry.handler,entry.name)
        registry.register(**fields,override=True)


def register_delivery_tools(sandbox,quality,*,on_terminal=None):
    from .quality import DeliveryTools
    from tools.registry import registry
    operations=DeliveryTools(sandbox,quality)
    if sandbox.run.reviewing:
        name='delivery_review'
        schema=dict(type='object',additionalProperties=False,required=['decision','reason','findings'],properties=dict(
            decision={'type':'string','enum':['approve','changes']},reason={'type':'string','minLength':1,'maxLength':2000},
            findings=dict(type='array',maxItems=8,items=dict(type='object',additionalProperties=False,
                required=['path','line','detail'],properties=dict(path={'type':'string'},
                    line={'type':'integer','minimum':1},detail={'type':'string','minLength':1,'maxLength':2000})))))
        operation=operations.review
        description='Submit independent review of the existing immutable delivery. Never recreate Red or edit the author work.'
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


def run_activity(sandbox,quality,route,prompt,*,run_seconds=600):
    """Trusted SDK adapter; no lifecycle inference from the assistant's prose.

    Route comes from controller configuration, not a model tool argument.
    Qualification is loopback-only. Production provider release remains a
    separate installation/authorization step; no fallback route is configured.
    """
    if (not isinstance(route,dict) or set(route)!={'base_url','api_key','provider','api_mode','model'}
            or any(not isinstance(v,str) or not v for v in route.values())
            or type(run_seconds) is not int or not 1<=run_seconds<=3600):
        raise ValueError('explicit bounded controller model route required')
    url=urlsplit(route['base_url'])
    if url.username or url.password or sandbox.project.qualification and (url.scheme!='http' or url.hostname!='127.0.0.1'):
        raise ValueError('qualification model route must be loopback only')
    from hermes_cli.profiles import get_active_profile_name
    if get_active_profile_name()!=sandbox.run.actor:raise ValueError('worker must bind the assigned profile')
    install_backend(sandbox)
    from run_agent import AIAgent
    from hermes_state import SessionDB
    from toolsets import create_custom_toolset
    db=SessionDB();agent=None;terminal={}
    def finished(result):
        terminal.update(result)
        agent.interrupt(tool_reason='delivery_handoff')
    gates,operations=register_delivery_tools(sandbox,quality,on_terminal=finished)
    allowed=tool_names(sandbox)|gates
    create_custom_toolset('fabriquinha_activity','Controller-selected delivery activity',tools=sorted(allowed))
    anchor='fabriquinha-'+digest(dict(project=sandbox.project.fingerprint(),subject=sandbox.run.subject(),
        model=route['model'],provider=route['provider'],api_mode=route['api_mode']))[:32]
    session=db.resolve_resume_session_id(anchor);previous=db.get_session(session)
    try:
        history=None
        if previous:
            if previous['profile_name']!=sandbox.run.actor:raise ValueError('session belongs to another profile')
            db.assert_resume_safe(session);history,_=db.get_resume_conversations(session)
        phase=('Review existing immutable delivery; never write or recreate Red. Submit findings using delivery_review.'
               if sandbox.run.reviewing else 'Implement the current phase with real tests and use delivery_submit. '
               'Validation errors require correction, not weakening tests. Do not claim completion in prose.')
        agent=AIAgent(**route,max_iterations=40,enabled_toolsets=['fabriquinha_activity'],disabled_toolsets=['kanban'],
            quiet_mode=True,skip_context_files=True,skip_memory=True,skip_background_review=True,
            session_db=db,session_id=session,cwd='/workspace',run_budget_seconds=run_seconds,
            fallback_model=None,ephemeral_system_prompt=phase)
        if agent.valid_tool_names!=allowed:raise ValueError('native tool surface diverged from phase policy')
        restrict_handlers(sandbox,allowed)
        if sandbox.run.reviewing:
            prompt+='\nController-recorded TDD evidence (historical Red is not to be reproduced):\n'+json.dumps(operations.evidence())
        result=agent.run_conversation(prompt,conversation_history=history,
                                     system_message=previous.get('system_prompt') if previous else None)
        if not terminal:raise ValueError('activity ended without a controller-validated native handoff')
        return dict(transition=terminal,session=agent.session_id,resumed=bool(previous),
                    sdk_exit=result.get('exit_reason'),delivery_approval=False)
    finally:
        if agent:agent.close()
        db.close();sandbox.close()
