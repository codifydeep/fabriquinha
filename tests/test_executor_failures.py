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
