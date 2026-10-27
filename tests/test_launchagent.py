import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('launchagent',Path(__file__).resolve().parents[1]/'scripts/prepare_hermes_launchagent.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class NativeSupervisor(unittest.TestCase):
    def test_pinned_foreground_service_does_not_enable_or_resume_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(module,'command'):
            root=Path(temporary)
            for file,value in (('project.json',dict(namespace='delivery-kit-proof',qualification=False)),
                               ('control.json',dict(paused=True)),('provider-policy.json',dict(enabled=False))):
                (root/file).write_text(json.dumps(value))
            result=module.prepare(root,'a'*64,root/'python',root,root/'upstream')
            target=Path(result['plist']);job=plistlib.loads(target.read_bytes())
            self.assertEqual(job['KeepAlive'],{'Crashed':True})
            self.assertEqual(job['ThrottleInterval'],60)
            self.assertTrue(job['AbandonProcessGroup'])
            self.assertEqual(job['Umask'],0o077)
            self.assertIn('serve',job['ProgramArguments']);self.assertNotIn('resume',job['ProgramArguments'])
            self.assertEqual(set(job['EnvironmentVariables']),{'PATH','HOME','PYTHONNOUSERSITE','PYTHONSAFEPATH'})
            before=target.read_bytes()
            with self.assertRaises(FileExistsError):module.prepare(root,'b'*64,root/'python',root,root/'upstream')
            self.assertEqual(target.read_bytes(),before)
            (root/'provider-policy.json').write_text('{"enabled":true}')
            with self.assertRaisesRegex(ValueError,'disabled'):module.prepare(root,'a'*64,root/'python',root,root/'upstream')
