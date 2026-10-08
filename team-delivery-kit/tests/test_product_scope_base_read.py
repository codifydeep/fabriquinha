import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from test_portable_contract import contract
from broker.product_scope_revision import digest
from broker.product_scope_base_read import inspect


class ProductScopeBaseReadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.contract=contract();self.sha='a'*40
        files={'AGENTS.md':b'Preserve tests.','app.py':b'pass\n','tests/test_old.py':b'pass\n',
               'contract.json':json.dumps(self.contract,sort_keys=True).encode()}
        for name,data in files.items():
            path=self.base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.manifest=dict(base_sha=self.sha,files={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
        encoded=json.dumps(self.manifest,sort_keys=True).encode();(self.base/'manifest.json').write_bytes(encoded)
        self.manifest_sha=hashlib.sha256(encoded).hexdigest()

    def run_read(self):return inspect(self.base,self.sha,self.manifest_sha,digest(self.contract))

    def test_read_confirms_actual_original_contract_without_authorization_or_changes(self):
        before={str(p.relative_to(self.base)):p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        result=self.run_read()
        self.assertEqual(result['contract'],self.contract)
        self.assertFalse(result['write_grant_issued']);self.assertFalse(result['delivery_approval'])
        self.assertEqual(before,{str(p.relative_to(self.base)):p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_modified_baseline_cannot_sponsor_scope_replanning(self):
        (self.base/'app.py').write_bytes(b'changed\n')
        with self.assertRaises(ValueError):self.run_read()

    def test_wrong_git_manifest_or_contract_identity_is_rejected(self):
        for args in (('b'*40,self.manifest_sha,digest(self.contract)),
                     (self.sha,'b'*64,digest(self.contract)),(self.sha,self.manifest_sha,'c'*64)):
            with self.subTest(args=args),self.assertRaises(ValueError):inspect(self.base,*args)

    def test_symlink_or_foreign_artifact_cannot_be_read(self):
        foreign=self.base/'foreign';foreign.write_text('not a registered file')
        with self.assertRaises(ValueError):self.run_read()
        foreign.unlink();foreign.symlink_to(self.base/'app.py')
        with self.assertRaises(ValueError):self.run_read()
