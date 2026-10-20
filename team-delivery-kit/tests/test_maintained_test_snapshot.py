import hashlib
import json
import os
import unittest
from pathlib import Path

import test_test_first_protocol as fixture
from maintained_test_snapshot import project


class MaintainedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.TestFirstProtocolTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.base,self.source,self.dest=self.f.base,self.f.work,self.f.red
        self.seal()
    def seal(self):
        names=[p for p in self.source.rglob('*') if p.is_file() and p.name not in ('manifest.json','.delivery-kit-base.json')]
        marker=self.source/'.delivery-kit-base.json'
        if marker.exists():marker.unlink()
        self.raw=json.dumps(dict(files={str(p.relative_to(self.source)):dict(bytes=p.stat().st_size,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in names}),sort_keys=True,separators=(',',':')).encode()
        (self.source/'manifest.json').write_bytes(self.raw)
        self.selection=dict(base_manifest_sha256=hashlib.sha256((self.base/'manifest.json').read_bytes()).hexdigest(),
            candidate_manifest_sha256=hashlib.sha256(self.raw).hexdigest(),
            test_sha256={'tests/test_new.py':hashlib.sha256((self.source/'tests/test_new.py').read_bytes()).hexdigest()})
    def run_projection(self):return project(self.base,self.source,self.dest,self.selection)
    def test_exact_projection_is_idempotent_and_is_not_red(self):
        before={str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        p=self.run_projection();self.assertEqual(p,self.run_projection())
        self.assertEqual(p['manifest_sha256'],self.selection['candidate_manifest_sha256'])
        self.assertEqual(p['test_sha256'],self.selection['test_sha256']);self.assertNotIn('exit_code',p)
        self.assertEqual(before,{str(p.relative_to(self.dest)):p.read_bytes() for p in self.dest.rglob('*') if p.is_file()})
        self.assertTrue(all((p.stat().st_mode & 0o777)==0o400 for p in self.dest.rglob('*') if p.is_file()))
    def test_baseline_changes_rejected_even_with_a_consistent_source_manifest(self):
        (self.source/'app.py').write_bytes(b'changed');self.seal()
        with self.assertRaises(ValueError):self.run_projection()
        self.assertEqual(list(self.dest.iterdir()),[])
    def test_wrong_test_hash_and_stale_manifest_fail_before_writes(self):
        self.selection['test_sha256']['tests/test_new.py']='0'*64
        with self.assertRaises(ValueError):self.run_projection()
        self.assertEqual(list(self.dest.iterdir()),[])
        self.seal();(self.source/'tests/test_new.py').write_bytes(b'drift')
        with self.assertRaises(ValueError):self.run_projection()
        self.assertEqual(list(self.dest.iterdir()),[])
    def test_symlink_extra_file_and_existing_destination_drift_are_rejected(self):
        (self.source/'extra').write_bytes(b'x');self.seal()
        with self.assertRaises(ValueError):self.run_projection()
        (self.source/'extra').unlink();self.seal();self.run_projection()
        (self.dest/'app.py').chmod(0o600);(self.dest/'app.py').write_bytes(b'drift')
        with self.assertRaises(ValueError):self.run_projection()
    def test_hardlinked_source_is_not_an_immutable_input(self):
        external=self.source.parent/'hardlink';os.link(self.source/'app.py',external)
        with self.assertRaises(ValueError):self.run_projection()
        self.assertEqual(list(self.dest.iterdir()),[])
