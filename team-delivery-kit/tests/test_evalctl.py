import contextlib
import io
import os
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import evalctl


class BootstrapTests(unittest.TestCase):
    def test_optional_component_status_detects_stopped_runtime_without_environment_leak(self):
        def inspect(command, **_):
            service = command[-1].removeprefix('delivery-kit-eval-').removesuffix('-1')
            container = {'Config': {'Labels': {'com.docker.compose.project': evalctl.PROJECT,
                                                'com.docker.compose.service': service},
                                    'Env': ['OPENROUTER_API_KEY=do-not-print']},
                         'State': {'Status': 'exited' if service == 'runtime' else 'running',
                                   'ExitCode': 0},
                         'HostConfig': {'RestartPolicy': {'Name': 'no'}}}
            return SimpleNamespace(returncode=0, stdout=json.dumps([container]))
        with patch.object(evalctl.subprocess, 'run', side_effect=inspect):
            result = evalctl.component_status()
        self.assertEqual(result['runtime']['state'], 'exited')
        self.assertEqual(result['execution-broker']['state'], 'running')
        self.assertEqual(result['model-proxy']['state'], 'running')
        self.assertEqual(result['runtime']['violations'], ['unexpected_credential_environment'])
        self.assertNotIn('do-not-print', json.dumps(result))

    def test_status_fails_when_execution_component_is_stopped(self):
        output = io.StringIO()
        with patch.object(evalctl, 'compose'), patch.object(evalctl, 'component_status',
                return_value={'runtime': {'state': 'exited'}, 'execution-broker': {'state': 'running'}}):
            with contextlib.redirect_stdout(output):
                self.assertEqual(evalctl.status(), 1)
        self.assertIn('exited', output.getvalue())

    def test_private_init_is_idempotent_and_does_not_print_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / '.local'
            env_file = private / 'evaluation.env'
            output = io.StringIO()
            with patch.object(evalctl, 'PRIVATE', private), patch.object(evalctl, 'ENV_FILE', env_file):
                with contextlib.redirect_stdout(output):
                    evalctl.initialize()
                    original = env_file.read_text()
                    evalctl.initialize()
                self.assertEqual(env_file.read_text(), original)
                self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
                self.assertEqual(private.stat().st_mode & 0o777, 0o700)
                for line in original.splitlines():
                    self.assertNotIn(line.split('=', 1)[1], output.getvalue())

    def test_does_not_import_shell_credentials_into_compose(self):
        with patch.dict(os.environ, {'EVAL_DB_PASSWORD': 'injected', 'OPENROUTER_API_KEY': 'secret', 'PATH': '/bin'}, clear=True):
            self.assertEqual(evalctl.process_env(), {'PATH': '/bin'})

    def test_refuses_symlink_private_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.mkdir()
            private = Path(directory) / '.local'
            private.symlink_to(target)
            with patch.object(evalctl, 'PRIVATE', private), patch.object(evalctl, 'ENV_FILE', private / 'evaluation.env'):
                with self.assertRaises(ValueError):
                    evalctl.initialize()
            self.assertEqual(list(target.iterdir()), [])

    def test_refuses_world_readable_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            env_file = private / 'evaluation.env'
            env_file.write_text('EVAL_DB_PASSWORD=test')
            env_file.chmod(0o644)
            with patch.object(evalctl, 'PRIVATE', private), patch.object(evalctl, 'ENV_FILE', env_file):
                with self.assertRaises(ValueError):
                    evalctl.check_private()


if __name__ == '__main__':
    unittest.main()
