import hashlib
import json
from pathlib import Path
import shutil
import unittest
from test_initial_base_validation import InitialInspectionTests
from broker.recovery_snapshot_inspect import inspect


class RecoverySnapshotTests(unittest.TestCase):
    def setUp(self):
        f=InitialInspectionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.base=f.root;self.snapshot=Path(f.tmp.name+'-snapshot');self.snapshot.mkdir()
        self.addCleanup(shutil.rmtree,self.snapshot)
        for name in ('AGENTS.md','app.py','tests/test_old.py'):
            p=self.snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.base/name,p)
        (self.snapshot/'tests/test_new.py').write_bytes(b'def test_new():\n    assert False\n')
        self.red={'tests/test_new.py':hashlib.sha256((self.snapshot/'tests/test_new.py').read_bytes()).hexdigest()}
        self.manifest()

    def manifest(self):
        files={str(p.relative_to(self.snapshot)):dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
               for p in self.snapshot.rglob('*') if p.is_file() and p.name!='manifest.json'}
        (self.snapshot/'manifest.json').write_text(json.dumps(dict(files=files)))

    def test_no_product_edit_is_a_valid_preservation_not_a_delivery(self):
        proof=inspect(self.base,self.snapshot,self.red)
        self.assertEqual(proof['changed_code_count'],0);self.assertFalse(proof['delivery_approval'])
        self.assertTrue(proof['frozen_tests_unchanged'])

    def test_absent_unfinished_product_file_is_not_required_for_preservation(self):
        spec=json.loads((self.base/'contract.json').read_text())
        spec['files'].append('future.py');spec['editable_files'].append('future.py')
        (self.base/'contract.json').write_text(json.dumps(spec))
        manifest=json.loads((self.base/'manifest.json').read_text())
        manifest['files']['contract.json']=hashlib.sha256((self.base/'contract.json').read_bytes()).hexdigest()
        (self.base/'manifest.json').write_text(json.dumps(manifest))
        self.assertFalse(inspect(self.base,self.snapshot,self.red)['delivery_approval'])

    def test_changed_baseline_or_frozen_new_test_are_rejected_even_with_fresh_manifest(self):
        old=self.snapshot/'tests/test_old.py';old.write_bytes(b'changed');self.manifest()
        with self.assertRaises(ValueError):inspect(self.base,self.snapshot,self.red)
        shutil.copyfile(self.base/'tests/test_old.py',old)
        (self.snapshot/'tests/test_new.py').write_bytes(b'changed');self.manifest()
        with self.assertRaises(ValueError):inspect(self.base,self.snapshot,self.red)
