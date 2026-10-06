"""Explicit Docker smoke for Python-tool writes under the worker UID."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

from test_portable_contract import contract


IMAGE = os.environ.get('LOCKDOWN_TEST_IMAGE', 'delivery-kit-eval-broker:20260930.52')


@unittest.skipUnless(os.environ.get('RUN_LOCKDOWN_DOCKER_TEST') == '1',
                     'Docker smoke runs explicitly')
class WorkspaceLockdownDockerTests(unittest.TestCase):
    def test_real_file_handlers_obey_phase_fence(self):
        volume = 'delivery-kit-lockdown-smoke-' + uuid.uuid4().hex[:12]
        subprocess.run(['docker', 'volume', 'create', '--name', volume,
                        '--label', 'delivery-kit.owner=lockdown-smoke'],
                       check=True, capture_output=True)
        mount = ['--mount', f'type=volume,source={volume},target=/workspace']
        try:
            setup = ('from pathlib import Path; import os; '
                     'Path("/workspace/allowed.py").write_text("old\\n"); '
                     'Path("/workspace/frozen.py").write_text("frozen\\n"); '
                     'os.chmod("/workspace/allowed.py",0o666); '
                     'os.chmod("/workspace/frozen.py",0o444); '
                     'os.chmod("/workspace",0o555)')
            subprocess.run(['docker', 'run', '--rm', '--network', 'none',
                            *mount, '--entrypoint', 'python', IMAGE, '-c', setup],
                           check=True, capture_output=True)
            probe = '''import subprocess
from pathlib import Path
from tools.file_operations import ShellFileOperations
class Local:
    cwd = '/workspace'
    def execute(self, command, cwd=None, stdin_data=None, **kwargs):
        result = subprocess.run(command, shell=True, cwd=cwd, input=stdin_data,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return {'output': result.stdout, 'returncode': result.returncode}
tools = ShellFileOperations(Local())
result = tools.write_file('/workspace/allowed.py', 'new = 1\\n')
assert not result.error, result
result = tools.patch_replace('/workspace/allowed.py', 'new = 1', 'new = 2')
assert not result.error, result
assert Path('/workspace/allowed.py').read_text() == 'new = 2\\n'
assert tools.write_file('/workspace/frozen.py', 'bad').error
assert tools.write_file('/workspace/rogue.py', 'bad').error
assert Path('/workspace/frozen.py').read_text() == 'frozen\\n'
print('real write_file and patch passed; frozen and undeclared files denied')
'''
            result = subprocess.run(['docker', 'run', '--rm', '--network', 'none',
                                     '--read-only', '--user', '10000:10000',
                                     '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                     '--tmpfs', '/tmp:rw,nosuid,nodev',
                                     '--env', 'HERMES_FENCED_INPLACE_WRITES=1',
                                     '--env', 'HERMES_WRITE_SAFE_ROOT=/workspace',
                                     *mount, '--entrypoint', 'python', IMAGE, '-c', probe],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True)

    def test_python_cannot_write_outside_phase_file(self):
        volume = 'delivery-kit-lockdown-smoke-' + uuid.uuid4().hex[:12]
        subprocess.run(['docker', 'volume', 'create', '--name', volume,
                        '--label', 'delivery-kit.owner=lockdown-smoke'],
                       check=True, capture_output=True, text=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                data = json.dumps(contract()).encode()
                (base / 'contract.json').write_bytes(data)
                hashes = {'contract.json': hashlib.sha256(data).hexdigest()}
                for filename, content in {'AGENTS.md': b'policy\n', 'app.py': b'x = 1\n',
                                          'tests/test_old.py': b'def test_old(): pass\n'}.items():
                    path = base / filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    hashes[filename] = hashlib.sha256(content).hexdigest()
                manifest = json.dumps({'base_sha': 'a' * 40, 'files': hashes}).encode()
                (base / 'manifest.json').write_bytes(manifest)
                mounts = ['--mount', f'type=bind,source={base},target=/base,readonly',
                          '--mount', f'type=volume,source={volume},target=/workspace']

                def run(uid, command, *, allowed=None, repair=None):
                    args = ['docker', 'run', '--rm', '--network', 'none', '--read-only',
                            '--user', uid, '--cap-drop', 'ALL']
                    if uid == '0:0':
                        args += ['--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE']
                    args += ['--security-opt', 'no-new-privileges', *mounts]
                    if allowed is not None:
                        args += ['--env', 'WORKSPACE_ALLOWED_JSON=' + json.dumps(allowed)]
                    if repair is not None:
                        args += ['--env','WORKSPACE_REPAIR_INPUT_JSON='+json.dumps(repair)]
                    args += ['--entrypoint', 'python', IMAGE, *command]
                    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

                subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                                '--user', '10000:10000', '--cap-drop', 'ALL', *mounts,
                                '--env', 'BASE_MANIFEST_SHA256=' + hashlib.sha256(manifest).hexdigest(),
                                '--entrypoint', 'python', IMAGE, '/seed_workspace.py'],
                               check=True, capture_output=True, text=True)
                probe = (
                    'import json, os\nfrom pathlib import Path\n'
                    'out = {}\n'
                    'for name in ("tests/test_new.py", "tests/test_old.py", '
                    '"tests/rogue.py", "app.py"):\n'
                    '  try:\n    Path("/workspace", name).write_text("changed\\n")\n'
                    '    out[name] = "written"\n'
                    '  except PermissionError:\n    out[name] = "denied"\n'
                    'try:\n  os.chmod("/workspace/tests/test_old.py", 0o666)\n'
                    '  out["chmod_old"] = "changed"\n'
                    'except PermissionError:\n  out["chmod_old"] = "denied"\n'
                    'print(json.dumps(out))\n')
                payload=b'#'+b'x'*38509
                run('0:0',['-c','from pathlib import Path; Path("/workspace/tests/test_new.py").write_bytes(b"#"+b"x"*38509)'])
                with self.assertRaises(subprocess.CalledProcessError):
                    run('0:0', ['/workspace_lockdown.py'], allowed=['tests/test_new.py'])
                repair={'tests/test_new.py':{'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}}
                run('0:0', ['/workspace_lockdown.py'], allowed=['tests/test_new.py'],repair=repair)
                first = json.loads(run('10000:10000', ['-c', probe]))
                self.assertEqual(first, {'tests/test_new.py': 'written',
                                         'tests/test_old.py': 'denied',
                                         'tests/rogue.py': 'denied', 'app.py': 'denied',
                                         'chmod_old': 'denied'})
                run('0:0', ['/workspace_lockdown.py'], allowed=['app.py'])
                second = json.loads(run('10000:10000', ['-c', probe]))
                self.assertEqual(second['app.py'], 'written')
                self.assertEqual(second['tests/test_new.py'], 'denied')
                self.assertEqual(second['tests/rogue.py'], 'denied')
        finally:
            subprocess.run(['docker', 'volume', 'rm', volume], check=True,
                           capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
