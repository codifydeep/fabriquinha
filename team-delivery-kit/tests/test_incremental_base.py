import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from test_portable_contract import contract
from broker.incremental_base import derive_contract,materialize


class IncrementalBaseTests(unittest.TestCase):
    def test_v2_new_test_remains_required_and_prior_tests_become_protected(self):
        previous=dict(self.contract,schema_version=2,required_files=list(self.contract['files']))
        result=derive_contract(previous,'tests/test_unit2.py')
        self.assertIn('tests/test_unit2.py',result['required_files'])
        self.assertTrue(set(previous['test_files'])<=set(result['protected_files']))
        self.assertFalse(set(previous['test_files'])&set(result['editable_files']))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'snapshot';self.source.mkdir()
        self.target=Path(self.temp.name)/'base';self.target.mkdir()
        self.contract=contract();files={}
        for name in self.contract['files']:
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True)
            data=b'original checkpoint bytes\n';p.write_bytes(data)
            files[name]=dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
        manifest=json.dumps({'files':files},sort_keys=True).encode()
        (self.source/'manifest.json').write_bytes(manifest)
        self.sha=hashlib.sha256(manifest).hexdigest()

    def copy(self,resume=False):
        return materialize(self.source,self.target,self.contract,'tests/test_unit2.py',self.sha,'a'*40,resume=resume)

    def test_next_base_has_distinct_hash_and_protects_all_previous_tests(self):
        receipt=self.copy()
        self.assertNotEqual(receipt['base_manifest_sha256'],receipt['checkpoint_manifest_sha256'])
        next_contract=json.loads((self.target/'contract.json').read_text())
        self.assertTrue(set(self.contract['test_files'])<=set(next_contract['protected_files']))
        self.assertFalse(set(self.contract['test_files'])&set(next_contract['editable_files']))
        for name in self.contract['files']:
            self.assertEqual((self.target/name).read_bytes(),(self.source/name).read_bytes())
        self.assertEqual(self.copy(resume=True),receipt)

    def test_interrupted_copy_resumes_without_overwriting_or_rewriting_checkpoint(self):
        original=(self.source/'manifest.json').read_bytes()
        name=self.contract['files'][0];p=self.target/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((self.source/name).read_bytes())
        self.copy(resume=True)
        self.assertEqual((self.source/'manifest.json').read_bytes(),original)

    def test_changed_snapshot_or_partial_base_fails_closed(self):
        name=self.contract['files'][0];(self.source/name).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.copy()
        self.assertEqual(list(self.target.iterdir()),[])

    def test_existing_test_path_outside_root_and_symlinks_are_rejected(self):
        for name in [self.contract['test_files'][0],'other/test_unit2.py','../test_unit2.py']:
            with self.assertRaises(ValueError):derive_contract(self.contract,name)
        name=self.contract['files'][0];p=self.source/name;p.unlink();p.symlink_to(self.source/'manifest.json')
        with self.assertRaises(ValueError):self.copy()

    def test_destination_inside_snapshot_cannot_change_immutable_input(self):
        with self.assertRaises(ValueError):
            materialize(self.source,self.source/'nested',self.contract,'tests/test_unit2.py',self.sha,'a'*40)
        self.assertFalse((self.source/'nested').exists())
