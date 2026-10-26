"""Host executor failure receipts; fixed fake Docker transport, no daemon."""
import json
import base64
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store, digest
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked, Journal
from fabriquinha.executor import Runner
from test_delivery_core import configuration


class FailedJobRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = Store(root/'private')
        source = root/'source'
        source.mkdir()
        (source/'app.py').write_text('pass\n')
        self.snapshot = self.store.capture(source)
        self.runner = Runner.__new__(Runner)
        self.runner.project = Project.parse(configuration())
        self.runner.store = self.store
        self.runner.journal = Journal(self.store.root/'effects')
        self.run = SimpleNamespace(binding=lambda: dict(task='t_test', number=1))
        self.state = 'created'
        self.calls = []
        self.failure = 'timeout'
        self.output = '{}'

    def inspect(self, *_):
        return dict(Image=self.runner.project.validation_image, Mounts=[], State=dict(
            Running=self.state == 'running', Status=self.state,
            Error='failed sandbox start' if self.failure == 'start' else '', ExitCode=137))

    def docker(self, *args, **_):
        self.calls.append(args)
        if args[0] == 'create':
            return 'a'*64
        if args[0] == 'start':
            if self.failure == 'start':
                raise subprocess.CalledProcessError(1, ['docker', 'start'])
            self.state = 'running'
            return 'a'*64
        if args[0] == 'wait':
            if self.failure == 'timeout':
                raise subprocess.TimeoutExpired(['docker', 'wait'], 1)
            self.state = 'exited'
            return '137'
        if args[0] == 'stop':
            self.state = 'exited'
            return 'a'*64
        if args[0] == 'logs':
            return self.output
        if args[0] == 'rm':
            self.state = 'removed'
            return 'a'*64
        raise AssertionError(args)

    def check_failure(self):
        with patch('fabriquinha.executor.docker', self.docker), patch.object(self.runner, 'inspect', self.inspect):
            # Lost start acknowledgement must first be observed, not repeated.
            if self.failure == 'start':
                from fabriquinha.effects import Pending
                with self.assertRaises(Pending):
                    self.runner.run(self.run, self.snapshot, 'green')
            with self.assertRaises(EffectBlocked):
                self.runner.run(self.run, self.snapshot, 'green')
            receipts = list((self.store.root/'jobs').glob('*/result.json'))
            self.assertEqual(len(receipts), 1)
            saved = json.loads(receipts[0].read_bytes())
            receipt = self.store.receipt(saved['receipt'], kind='suite_job')
            self.assertTrue(receipt['payload']['infrastructure_error'])
            self.assertTrue((receipts[0].parent/'retired-metadata.json').is_file())
            self.assertEqual(self.state, 'removed')
            with self.assertRaises(EffectBlocked):
                self.runner.run(self.run, self.snapshot, 'green')
        self.assertEqual(sum(c[0] == 'create' for c in self.calls), 1)
        self.assertEqual(sum(c[0] == 'start' for c in self.calls), 1)
        self.assertEqual(sum(c[0] == 'rm' for c in self.calls), 1)

    def test_timeout_is_archived_retired_and_never_restarted(self):
        self.check_failure()

    def test_browser_capability_requires_a_qualified_image_label(self):
        project=Project.parse({**configuration(),'browser_tdd':True})
        image=dict(Id=project.validation_image,Config=dict(User='65534:65534',
            Entrypoint=['python','-B','/opt/fabriquinha/suite.py'],Labels={}))
        with patch('fabriquinha.executor.docker',return_value=json.dumps([image])):
            with self.assertRaisesRegex(ValueError,'browser TDD image capability'):Runner(project,self.store)
        image['Config']['Labels']['fabriquinha.browser-tdd']='1'
        with patch('fabriquinha.executor.docker',return_value=json.dumps([image])):
            self.assertIsInstance(Runner(project,self.store),Runner)

    def test_browser_profile_keeps_readonly_no_network_and_bounded_resources(self):
        self.runner.project=Project.parse({**configuration(),'browser_tdd':True})
        with patch.object(self.runner,'_execute',return_value='fixture-job') as execute:
            self.runner.run(self.run,self.snapshot,'red')
        command=execute.call_args.args[2]
        self.assertEqual(command[command.index('--memory')+1],'512m')
        self.assertEqual(command[command.index('--pids-limit')+1],'128')
        self.assertEqual(command[command.index('--network')+1],'none')
        self.assertIn('--read-only',command)
        self.assertIn('/tmp:rw,noexec,nosuid,size=128m',command)
        self.assertTrue(command[-2].endswith(',dst=/workspace,readonly'))

    def test_frozen_preview_binds_trusted_scripts_and_is_mandatory_only_for_delivery_phases(self):
        value={**configuration(),'browser_tdd':True,'browser_image':'sha256:'+'b'*64,
            'coordination_roles':{'product':'backend','lead':'lead'},
            'delivery_roles':{'tests':'backend','integration':'lead'}}
        self.runner.project=Project.parse(value)
        for phase in ('green','delivery','integrated','red','control','diagnostic'):
            with patch.object(self.runner,'_execute',return_value='fixture-job') as execute:
                self.runner.run(self.run,self.snapshot,phase)
            _,identity,command=execute.call_args.args
            if phase not in ('green','delivery','integrated'):
                self.assertNotIn('qa_preview',identity);continue
            self.assertEqual(set(identity['qa_preview']),{'reporter','driver'})
            mounts=[command[i+1] for i,arg in enumerate(command) if arg=='--mount']
            self.assertEqual(len(mounts),3);self.assertTrue(all(m.endswith(',readonly') for m in mounts))
            self.assertIn('FABRIQUINHA_QA_PREVIEW='+self.snapshot,command)
            sources={m.split('dst=')[1].split(',')[0]:m.split('src=')[1].split(',')[0] for m in mounts}
            info=dict(Image=self.runner.project.validation_image,
                Config=dict(User='65534:65534',Entrypoint=['python','-B','/opt/fabriquinha/suite.py'],Cmd=None,
                    Labels={'fabriquinha.job':identity['key'],'com.docker.compose.project':self.runner.project.namespace+'-tests'},
                    Env=['FABRIQUINHA_TESTS_DIR=tests','FABRIQUINHA_QA_PREVIEW='+self.snapshot]),
                HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,CapDrop=['ALL']),
                Mounts=[dict(Type='bind',Destination=dest,Source=src,RW=False) for dest,src in sources.items()])
            with patch('fabriquinha.executor.docker',side_effect=lambda *args:json.dumps([info])):
                self.runner.inspect('fixture',identity)
                info['Mounts'][0]['RW']=True
                with self.assertRaises(ValueError):self.runner.inspect('fixture',identity)
                info['Mounts'][0]['RW']=False
                info['Config']['Entrypoint']=['sh']
                with self.assertRaises(ValueError):self.runner.inspect('fixture',identity)
            with patch('fabriquinha.executor.preview_drivers',return_value={'driver':'foreign'}):
                with patch('fabriquinha.executor.docker',return_value=json.dumps([info])):
                    with self.assertRaisesRegex(ValueError,'drivers changed'):self.runner.inspect('fixture',identity)

    def test_rejected_start_is_archived_retired_and_never_restarted(self):
        self.failure = 'start'
        self.check_failure()

    def test_timeout_fact_survives_lost_stop_acknowledgement(self):
        from fabriquinha.effects import Pending
        stop_sent = []
        def transport(*args, **kwargs):
            if args[0] == 'stop' and not stop_sent:
                stop_sent.append(True)
                self.state = 'exited'
                raise subprocess.TimeoutExpired(['docker', 'stop'], 1)
            return self.docker(*args, **kwargs)
        # Even plausible output cannot turn an expired execution into Green.
        self.output = '{"version":1,"tests_run":1,"cases":["test_ok"],"failures":[]}'
        with patch('fabriquinha.executor.docker', transport), patch.object(self.runner, 'inspect', self.inspect):
            with self.assertRaises(Pending):
                self.runner.run(self.run, self.snapshot, 'green')
            self.failure = 'none'
            with self.assertRaises(EffectBlocked):
                self.runner.run(self.run, self.snapshot, 'green')
        self.assertEqual(stop_sent, [True])

    def test_browser_screenshot_is_collected_from_stdout_not_disappearing_tmpfs(self):
        self.failure='none'
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lD8AAAAASUVORK5CYII=')
        self.output=json.dumps(dict(version=1,status='passed',png_base64=base64.b64encode(png).decode()))
        expected=dict(binding=self.run.binding(),project=self.runner.project.fingerprint(),snapshot=self.snapshot,
                      phase='browser',image='sha256:'+'b'*64,commit='a'*40)
        expected['key']=digest(expected)
        def transport(*args,**kwargs):
            if args[0]=='cp':raise subprocess.CalledProcessError(1,['docker','cp'])
            return self.docker(*args,**kwargs)
        with patch('fabriquinha.executor.docker',transport),patch.object(self.runner,'inspect',self.inspect):
            key=self.runner._execute(self.run,expected,['create'])
        receipt=self.store.receipt(key,kind='browser_job')['payload']
        self.assertTrue(receipt['screenshot_sha256'])
        self.assertNotIn('png_base64',receipt['report'])
        self.assertEqual((self.store.root/'jobs'/expected['key']/'screenshot.png').read_bytes(),png)


if __name__ == '__main__':
    unittest.main()
