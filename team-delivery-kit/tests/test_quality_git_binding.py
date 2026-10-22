"""Read-only exact Git/snapshot checks in real disposable local repositories."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
import quality_git_binding as binding
import test_quality_red_observation as fixtures


class GitBindingTests(unittest.TestCase):
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),'-c','user.name=Fixture',
            '-c','user.email=fixture@invalid','-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null',*args]).decode().strip()

    def setUp(self):
        f=fixtures.QualityRedObservationTests();f.setUp();self.addCleanup(f.doCleanups);f.prepare()
        self.f=f;self.repo=f.root/'repo';self.repo.mkdir();self.git('init','-q','-b','main')
        for name,raw in f.old.items():
            p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        self.git('add','.');self.git('commit','-qm','base');self.base=self.git('rev-parse','HEAD')
        self.plan={**f.plan,'base_sha':self.base}
        (self.repo/'tests/test_new.py').write_bytes(f.new);(self.repo/'app.py').write_bytes(b'VALUE=1\n')
        self.git('add','.');self.git('commit','-qm','candidate');self.commit=self.git('rev-parse','HEAD')
        self.snapshot=f.root/'delivered';self.snapshot.mkdir()
        for name in f.spec['files']:
            p=self.snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((self.repo/name).read_bytes())
        self.manifest()

    def manifest(self):
        facts={p:dict(sha256=hashlib.sha256((self.snapshot/p).read_bytes()).hexdigest(),
            bytes=len((self.snapshot/p).read_bytes())) for p in self.f.spec['files']}
        raw=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
        (self.snapshot/'manifest.json').write_bytes(raw);self.sha=hashlib.sha256(raw).hexdigest()

    def call(self):return binding.verify(self.repo,self.snapshot,self.sha,self.plan,self.commit,
        {**self.f.plan['baseline_tests'],**self.f.prepared['test_sha256']})

    def test_exact_commit_matches_every_snapshot_blob_without_mutating_checkout_or_approving(self):
        before=(self.git('rev-parse','HEAD'),self.git('status','--porcelain'))
        report=self.call()
        self.assertEqual(report['commit_sha'],self.commit);self.assertEqual(report['base_sha'],self.base)
        self.assertEqual(report['changed_paths'],['app.py','tests/test_new.py'])
        self.assertFalse(report['execution_authorized']);self.assertFalse(report['merge_authorized'])
        self.assertFalse(report['delivery_approval'])
        self.assertEqual(before,(self.git('rev-parse','HEAD'),self.git('status','--porcelain')))

    def test_other_sha_same_branch_or_snapshot_hash_does_not_prove_these_bytes(self):
        (self.repo/'app.py').write_bytes(b'VALUE=2\n');self.git('add','.');self.git('commit','-qm','other')
        self.commit=self.git('rev-parse','HEAD')
        with self.assertRaises(ValueError):self.call()
        self.commit=self.base
        with self.assertRaises(ValueError):self.call()

    def test_changed_blob_even_with_a_recomputed_snapshot_manifest_is_rejected(self):
        (self.snapshot/'app.py').write_bytes(b'VALUE=2\n');self.manifest()
        with self.assertRaises(ValueError):self.call()

    def test_out_of_scope_change_is_rejected_even_when_snapshot_matches(self):
        self.git('checkout','-q','-b','other',self.base)
        (self.repo/'tests/test_new.py').write_bytes(self.f.new);(self.repo/'app.py').write_bytes(b'VALUE=1\n')
        (self.repo/'AGENTS.md').write_bytes(b'Changed policy\n')
        (self.snapshot/'AGENTS.md').write_bytes(b'Changed policy\n');self.manifest()
        self.git('add','.');self.git('commit','-qm','invalid scope');self.commit=self.git('rev-parse','HEAD')
        with self.assertRaises(ValueError):self.call()

    def test_git_symlink_or_test_existing_in_original_base_is_not_adopted(self):
        self.git('checkout','-q','-b','symlink',self.base)
        p=self.repo/'app.py';p.unlink();p.symlink_to('AGENTS.md')
        (self.repo/'tests/test_new.py').write_bytes(self.f.new)
        self.git('add','.');self.git('commit','-qm','bad mode');self.commit=self.git('rev-parse','HEAD')
        with self.assertRaises(ValueError):self.call()

    def test_matching_commit_and_manifest_cannot_replace_independently_frozen_tests(self):
        self.git('checkout','-q','-b','weaken',self.base)
        weakened=self.f.new.replace(b'app.VALUE,1',b'app.VALUE,0')
        (self.repo/'tests/test_new.py').write_bytes(weakened)
        (self.repo/'app.py').write_bytes(b'VALUE=1\n')
        (self.snapshot/'tests/test_new.py').write_bytes(weakened);self.manifest()
        self.git('add','.');self.git('commit','-qm','weakened test');self.commit=self.git('rev-parse','HEAD')
        with self.assertRaises(ValueError):self.call()


if __name__=='__main__':unittest.main()
