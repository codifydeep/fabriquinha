"""A Git export is closed, reproducible and distinct from installation state."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.source import FILES, TREES, freeze, verify


class FrozenSource(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.cleanup)
        self.base=Path(self.temporary.name);self.repo=self.base/'repo';self.repo.mkdir()
        self.git('init','-q')
        for name in (*FILES,'src/fabriquinha/__init__.py','examples/python-http/bootstrap/app.py'):
            path=self.repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# '+name+'\n')
        (self.repo/'.gitignore').write_text('.local*/\n')
        (self.repo/'unrelated.txt').write_text('not part of runtime')
        self.git('add','.');self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        self.commit=self.git('rev-parse','HEAD').strip()
        self.target=self.base/'frozen'

    def cleanup(self):
        for root,dirs,files in os.walk(self.temporary.name):
            Path(root).chmod(0o700)
            for name in files:
                path=Path(root)/name
                if not path.is_symlink():path.chmod(0o600)
        self.temporary.cleanup()

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,stderr=subprocess.DEVNULL)

    def test_only_committed_runtime_and_operator_inputs_are_exported(self):
        (self.repo/'private.key').write_text('do not export')
        original=(self.repo/'src/fabriquinha/__init__.py').read_bytes()
        (self.repo/'src/fabriquinha/__init__.py').write_text('uncommitted implementation')
        result=freeze(self.repo,self.target,self.commit)
        self.assertEqual((self.target/'src/fabriquinha/__init__.py').read_bytes(),original)
        self.assertFalse((self.target/'private.key').exists())
        self.assertFalse((self.target/'unrelated.txt').exists())
        checked=verify(self.target,result['source_digest'])
        self.assertEqual(checked['commit'],self.commit)
        self.assertEqual(checked['files'],len(FILES)+2)
        self.assertEqual(result['model_calls'],0)
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(self.target.stat().st_mode&0o777,0o500)
        self.assertEqual((self.target/'src/fabriquinha/__init__.py').stat().st_mode&0o777,0o400)
        manifest=json.loads((self.target/'source-manifest.json').read_bytes())
        self.assertEqual(manifest['files']['src/fabriquinha/__init__.py'],hashlib.sha256(original).hexdigest())
        other=freeze(self.repo,self.base/'other',self.commit)
        self.assertEqual(other['source_digest'],result['source_digest'])

    def test_exact_commit_required_and_existing_directory_is_never_overwritten(self):
        for revision in ('HEAD','main','--all','a'*39,'b'*40):
            with self.subTest(revision=revision),self.assertRaises(ValueError):freeze(self.repo,self.target,revision)
            self.assertFalse(self.target.exists())
        self.target.mkdir();(self.target/'preserve').write_text('existing')
        with self.assertRaises(ValueError):freeze(self.repo,self.target,self.commit)
        self.assertEqual((self.target/'preserve').read_text(),'existing')

    def test_missing_runtime_input_or_git_symlink_fails_before_creating_export(self):
        path=self.repo/FILES[0];path.unlink()
        self.git('add','.');self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','missing')
        with self.assertRaises(ValueError):freeze(self.repo,self.target,self.git('rev-parse','HEAD').strip())
        self.assertFalse(self.target.exists())
        path.symlink_to('outside')
        self.git('add','.');self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','symlink')
        with self.assertRaises(ValueError):freeze(self.repo,self.target,self.git('rev-parse','HEAD').strip())
        self.assertFalse(self.target.exists())

    def test_unignored_export_inside_checkout_is_refused_but_private_root_allowed(self):
        with self.assertRaises(ValueError):freeze(self.repo,self.repo/'runtime',self.commit)
        result=freeze(self.repo,self.repo/'.local-install/source',self.commit)
        self.assertEqual(verify(self.repo/'.local-install/source',result['source_digest'])['commit'],self.commit)

    def test_changed_content_or_manifest_cannot_pass_external_digest(self):
        result=freeze(self.repo,self.target,self.commit);path=self.target/FILES[0]
        path.chmod(0o600);path.write_text('changed');path.chmod(0o400)
        with self.assertRaisesRegex(ValueError,'content'):verify(self.target,result['source_digest'])
        manifest=self.target/'source-manifest.json';manifest.chmod(0o600)
        value=json.loads(manifest.read_bytes());value['files'][FILES[0]]=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(value));manifest.chmod(0o400)
        with self.assertRaisesRegex(ValueError,'digest'):verify(self.target,result['source_digest'])

    def test_unexpected_files_symlinks_or_writable_source_fail_verification(self):
        result=freeze(self.repo,self.target,self.commit)
        self.target.chmod(0o700);extra=self.target/'extra.py';extra.write_text('extra');extra.chmod(0o400)
        self.target.chmod(0o500)
        with self.assertRaisesRegex(ValueError,'contents'):verify(self.target,result['source_digest'])
        self.target.chmod(0o700);extra.unlink();extra.symlink_to(self.repo/'private.key');self.target.chmod(0o500)
        with self.assertRaises(ValueError):verify(self.target,result['source_digest'])
        self.target.chmod(0o700);extra.unlink();self.target.chmod(0o500)
        (self.target/FILES[0]).chmod(0o600)
        with self.assertRaisesRegex(ValueError,'read-only'):verify(self.target,result['source_digest'])


if __name__=='__main__':unittest.main()
