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
        def guard(handler):
            @wraps(handler)
            def guarded(*args,**kwargs):
                sandbox.ensure()
                return handler(*args,**kwargs)
            return guarded
        fields={name:getattr(entry,name) for name in entry.__dataclass_fields__}
        fields['handler']=guard(entry.handler)
        registry.register(**fields,override=True)
