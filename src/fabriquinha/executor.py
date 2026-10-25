"""Fixed validation jobs with actual Docker facts and bounded effect recovery."""
import json
import hashlib
import base64
import binascii
from pathlib import Path
import subprocess
import sys
import time
from .artifacts import digest
from .effects import Journal, Pending, EffectBlocked, write_json

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'team-delivery-kit'))
from docker_grouping import args as grouping


def phase_mounts(workspace, tests_dir, phase, *, baseline_tests=()):
    """OS write boundaries, shared by the author adapter and its qualification."""
    workspace = Path(workspace).resolve()
    if phase not in {'tests', 'implementation', 'review'}:
        raise ValueError('controller-selected activity phase required')
    def bind(source, target, readonly):
        return ['--mount', f'type=bind,src={source},dst={target}'+(',readonly' if readonly else '')]
    result = bind(workspace, '/workspace', phase != 'implementation')
    if phase == 'tests':
        result += bind(workspace/tests_dir, '/workspace/'+tests_dir, False)
        for relative in baseline_tests:
            if not relative.startswith(tests_dir+'/') or '..' in Path(relative).parts:
                raise ValueError('baseline test outside configured discovery')
            result += bind(workspace/relative, '/workspace/'+relative, True)
    if phase == 'implementation':
        result += bind(workspace/tests_dir, '/workspace/'+tests_dir, True)
        from .quality import PROTECTED
        for relative in PROTECTED:
            source = workspace/relative
            if source.exists():
                result += bind(source, '/workspace/'+relative.rstrip('/'), True)
    return result


def docker(*args, timeout=30):
    return subprocess.run(['docker', *args], check=True, text=True, capture_output=True,
                          timeout=timeout).stdout


class Runner:
    """Trusted host service; exposes no arbitrary command or Docker operation."""
    def __init__(self, project, store):
        self.project, self.store = project, store
        self.journal = Journal(store.root / 'effects')
        image = json.loads(docker('image', 'inspect', project.validation_image))[0]
        if (image['Id'] != project.validation_image or image['Config'].get('Volumes')
                or image['Config'].get('User') != '65534:65534'
                or image['Config'].get('Entrypoint') != ['python', '-B', '/opt/fabriquinha/suite.py']):
            raise ValueError('canonical unprivileged fixed validator image required')
        if project.browser_tdd and (image['Config'].get('Labels') or {}).get('fabriquinha.browser-tdd')!='1':
            raise ValueError('qualified browser TDD image capability required')

    def inspect(self, name, expected):
        info = json.loads(docker('inspect', name))[0]
        if expected['phase']=='browser':
            return self.inspect_browser(info,expected)
        mounts = info.get('Mounts') or []
        binds = [m for m in mounts if m['Type'] != 'tmpfs']
        host, config = info['HostConfig'], info['Config']
        if (info['Image'] != self.project.validation_image or config.get('User') != '65534:65534'
                or config.get('Labels', {}).get('fabriquinha.job') != expected['key']
                or config.get('Labels', {}).get('com.docker.compose.project') != self.project.namespace+'-tests'
                or host.get('NetworkMode') != 'none' or host.get('Privileged')
                or not host.get('ReadonlyRootfs') or host.get('CapAdd')
                or 'ALL' not in (host.get('CapDrop') or [])
                or len(binds) != 1 or binds[0]['Destination'] != '/workspace' or binds[0]['RW']
                or Path(binds[0]['Source']).resolve() != self.store.tree(expected['snapshot'])
                or any(entry.split('=', 1)[0] in {'GH_TOKEN', 'GITHUB_TOKEN', 'OPENROUTER_API_KEY'}
                       for entry in config.get('Env', []))):
            raise ValueError('fixed job sandbox identity rejected')
        return info

    def inspect_browser(self,info,expected):
        config,host=info['Config'],info['HostConfig']
        mounts={m['Destination']:m for m in info.get('Mounts',[]) if m['Type']!='tmpfs'}
        sources={'/qa.py':ROOT/'src/fabriquinha/browser.py',
                 '/qa-contracts':self.store.tree(expected['snapshot'])/self.project.tests_dir}
        if (info['Image']!=self.project.browser_image or config.get('User')!='10000:10000'
                or config.get('Labels',{}).get('fabriquinha.job')!=expected['key']
                or config.get('Labels',{}).get('com.docker.compose.project')!=self.project.namespace+'-tests'
                or host.get('NetworkMode')!=self.project.namespace+'-homologation_qa'
                or set(info['NetworkSettings']['Networks'])!={self.project.namespace+'-homologation_qa'}
                or host.get('Privileged') or not host.get('ReadonlyRootfs') or host.get('CapAdd')
                or 'ALL' not in (host.get('CapDrop') or []) or set(mounts)!=set(sources)
                or any(mounts[p]['RW'] or Path(mounts[p]['Source']).resolve()!=source.resolve() for p,source in sources.items())
                or any(e.split('=',1)[0] in {'GH_TOKEN','GITHUB_TOKEN','OPENROUTER_API_KEY','TELEGRAM_BOT_TOKEN'}
                       for e in config.get('Env',[]))):
            raise ValueError('fixed browser job sandbox rejected')
        if hashlib.sha256((ROOT/'src/fabriquinha/browser.py').read_bytes()).hexdigest()!=expected['driver']:
            raise ValueError('browser driver changed during execution')
        return info

    def browser(self,run,snapshot,commit):
        if not self.project.browser_image:
            raise ValueError('explicit pinned browser toolchain required')
        image=json.loads(docker('image','inspect',self.project.browser_image))[0]
        if (image['Id']!=self.project.browser_image or image['Config'].get('Volumes')
                or image['Config'].get('User')!='10000:10000' or image['Config'].get('Entrypoint')!=['python']):
            raise ValueError('unprivileged fixed Python/browser toolchain required')
        network=json.loads(docker('network','inspect',self.project.namespace+'-homologation_qa'))[0]
        if not network['Internal'] or network.get('Labels',{}).get('com.docker.compose.project')!=self.project.namespace+'-homologation':
            raise ValueError('owned internal browser network required')
        expected=dict(binding=run.binding(),project=self.project.fingerprint(),snapshot=snapshot,
                      phase='browser',image=self.project.browser_image,commit=commit,
                      driver=hashlib.sha256((ROOT/'src/fabriquinha/browser.py').read_bytes()).hexdigest())
        key=digest(expected);expected['key']=key
        command=['create','--name',self.project.namespace+'-browser-'+key[:16],
            *grouping('browser',self.project.namespace),'--label','fabriquinha.job='+key,
            '--network',self.project.namespace+'-homologation_qa','--read-only','--user','10000:10000',
            '--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','512m','--cpus','1',
            '--pids-limit','256','--log-opt','max-size=1m','--log-opt','max-file=2',
            '--tmpfs','/tmp:rw,nosuid,size=256m','--env','FABRIQUINHA_SOURCE_SHA='+commit,
            '--mount',f'type=bind,src={ROOT/"src/fabriquinha/browser.py"},dst=/qa.py,readonly',
            '--mount',f'type=bind,src={self.store.tree(snapshot)/self.project.tests_dir},dst=/qa-contracts,readonly',
            self.project.browser_image,'-B','/qa.py']
        return self._execute(run,expected,command)

    def run(self, run, snapshot, phase):
        if phase not in {'baseline', 'red', 'green', 'control', 'delivery', 'integrated', 'diagnostic'}:
            raise ValueError('fixed suite operation required')
        expected = dict(binding=run.binding(), project=self.project.fingerprint(),
                        snapshot=snapshot, phase=phase, image=self.project.validation_image)
        key = digest(expected)
        expected['key'] = key
        name = self.project.namespace+'-'+phase+'-'+key[:16]
        command = ['create', '--name', name, *grouping('validation', self.project.namespace),
            '--label', 'fabriquinha.job='+key, '--network', 'none', '--read-only',
            '--user', '65534:65534', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '512m' if self.project.browser_tdd else '256m', '--cpus', '1', '--pids-limit', '128',
            '--log-opt', 'max-size=1m', '--log-opt', 'max-file=2',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m' if self.project.browser_tdd else '/tmp:rw,noexec,nosuid,size=64m', '--workdir', '/workspace',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'FABRIQUINHA_TESTS_DIR='+self.project.tests_dir,
            '--mount', f'type=bind,src={self.store.tree(snapshot)},dst=/workspace,readonly',
            self.project.validation_image]
        return self._execute(run,expected,command)

    def _execute(self,run,expected,command):
        key=expected['key']
        folder=self.store.root/'jobs'/key
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        receipt_path=folder/'result.json'
        name=self.project.namespace+'-'+expected['phase']+'-'+key[:16]
        kind='browser_job' if expected['phase']=='browser' else 'suite_job'

        def observe_create():
            try:
                return {'container':self.inspect(name,expected)['Id']}
            except subprocess.CalledProcessError:
                return None  # Unknown acknowledgements never authorize another create.

        if receipt_path.exists():
            saved = json.loads(receipt_path.read_bytes())
            receipt = self.store.receipt(saved['receipt'], kind=kind)
            if receipt['payload']['identity'] != expected:
                raise ValueError('job receipt identity drift')
            self.retire(saved['container'], expected, folder)
            if receipt['payload'].get('infrastructure_error'):
                raise EffectBlocked(receipt['payload']['infrastructure_error'])
            return saved['receipt']
        handle = self.journal.do(key+':create', expected,
            lambda: {'container': docker(*command).strip()}, observe_create)
        container = handle['container']
        self.inspect(container, expected)

        def observe_start():
            info = self.inspect(container, expected)
            if info['State']['Status'] == 'created' and info['State'].get('Error'):
                raise EffectBlocked('Docker rejected job start: '+info['State']['Error'])
            return {'container': container} if info['State']['Status'] in ('running', 'exited') else None

        deadline_path = folder / 'runtime.json'
        if not deadline_path.exists():
            write_json(deadline_path, dict(deadline=time.time()+self.project.timeout_seconds))
        runtime = json.loads(deadline_path.read_bytes())
        deadline, failure = runtime['deadline'], runtime.get('failure')
        if failure is None:
            try:
                self.journal.do(key+':start', expected,
                    lambda: {'container': docker('start', container).strip()}, observe_start)
            except EffectBlocked:
                state = self.inspect(container, expected)['State']
                if state['Status'] != 'created' or not state.get('Error'):
                    raise  # Unknown effects remain observable; never remove a possibly live job.
                failure = 'Docker rejected job start: '+state['Error']
        if failure is None:
            try:
                docker('wait', container, timeout=max(0.1, deadline-time.time()))
            except subprocess.TimeoutExpired:
                failure = 'validation job exceeded its persistent runtime'
                write_json(deadline_path, {**runtime, 'failure': failure})
        if failure == 'validation job exceeded its persistent runtime':
            self.journal.do(key+':stop', expected,
                lambda: {'container': docker('stop', '--time', '1', container).strip()},
                lambda: {'container': container} if not self.inspect(container, expected)['State']['Running'] else None)
        info = self.inspect(container, expected)
        if info['State']['Running'] or (info['State']['Status'] != 'exited' and failure is None):
            raise Pending('observe fixed suite termination')
        try:
            output = docker('logs', container)
        except subprocess.CalledProcessError as error:
            output = ''
            failure = failure or 'Docker logs unavailable: '+type(error).__name__
        write_json(folder / 'output.json', {'output': output[:2*1024*1024]})
        try:
            report = json.loads(output)
        except ValueError:
            report = None  # Preserve and retire the failed job; never count it as a test result.
        screenshot=None
        if kind=='browser_job' and report and report.get('status')=='passed':
            path=folder/'screenshot.png'
            try:
                encoded=report.pop('png_base64')
                if not isinstance(encoded,str) or len(encoded)>1400000:
                    raise ValueError('bounded regular browser screenshot required')
                png=base64.b64decode(encoded,validate=True)
                if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png)>1024*1024 or path.is_symlink():
                    raise ValueError('valid bounded PNG required')
                path.write_bytes(png)
                path.chmod(0o600)
                screenshot=hashlib.sha256(png).hexdigest()
            except (OSError,ValueError,KeyError,binascii.Error):
                failure='browser screenshot unavailable'
        sandbox=(dict(network=self.project.namespace+'-homologation_qa',snapshot='readonly',user='10000:10000')
                 if kind=='browser_job' else dict(network='none',snapshot='readonly',user='65534:65534'))
        payload = dict(identity=expected, exit_code=info['State']['ExitCode'], report=report,
            sandbox=sandbox,screenshot_sha256=screenshot,
            container=container, qualification=self.project.qualification, infrastructure_error=failure)
        receipt = self.store.record(kind, run.binding(), payload)
        write_json(receipt_path, dict(receipt=receipt, container=container))
        self.retire(container, expected, folder)
        if failure:
            raise EffectBlocked(failure)
        return receipt

    def retire(self, container, expected, folder):
        def observe():
            ids = docker('ps', '-aq', '--no-trunc', '--filter', 'id='+container).split()
            return {'retired': True} if container not in ids else None

        def remove():
            info = self.inspect(container, expected)
            if info['State']['Running']:
                raise ValueError('active validation job cannot be retired')
            write_json(folder / 'retired-metadata.json', dict(container=container, image=info['Image'],
                       state=info['State'], mounts=info['Mounts']))
            docker('rm', container)
            return {'retired': True}

        self.journal.do(expected['key']+':retire', expected, remove, observe)
