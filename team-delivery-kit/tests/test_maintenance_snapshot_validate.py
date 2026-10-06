import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from test_portable_contract import contract
from broker import maintenance_snapshot_validate as m


class MaintenanceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.base,self.previous,self.candidate=[Path(self.folder.name)/n for n in ('base','previous','candidate')]
        spec=contract()
        for key in ('files','editable_files','test_files'):
            spec[key]=[m.TEST if n=='tests/test_new.py' else n for n in spec[key]]
        contents={'AGENTS.md':'policy','app.py':'x=1','tests/test_old.py':'def test_old(): assert True'}
        for root in (self.base,self.previous,self.candidate):
            root.mkdir()
            for n,s in contents.items():
                (root/n).parent.mkdir(parents=True,exist_ok=True);(root/n).write_text(s)
        cb=json.dumps(spec).encode();(self.base/'contract.json').write_bytes(cb)
        baseline={n:hashlib.sha256((self.base/n).read_bytes()).hexdigest() for n in contents}
        baseline['contract.json']=hashlib.sha256(cb).hexdigest()
        (self.base/'manifest.json').write_text(json.dumps({'base_sha':'a'*40,'files':baseline}))
        self.original='DRIVER_BODY="function f(){"\ndef test_new(): assert True\n'
        (self.previous/m.TEST).write_text(self.original)
        (self.candidate/m.TEST).write_text(self.original.replace('function f(){','function f(){}'))
        self.freeze(self.previous);self.expected=self.freeze(self.candidate)
        self.oldsha=hashlib.sha256(self.original.encode()).hexdigest()
    def freeze(self,root):
        files={str(p.relative_to(root)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':len(p.read_bytes())}
            for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'}
        raw=json.dumps({'files':files}).encode();(root/'manifest.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    def verify(self):return m.verify(self.base,self.candidate,self.previous,self.expected,self.oldsha)
    def test_maintenance_is_not_product_delivery_and_uses_operator_suite(self):
        with patch.object(m.subprocess,'run',return_value=Mock(returncode=0)):
            result=self.verify()
        self.assertFalse(result['delivery_approval']);self.assertEqual(result['mode'],'driver_maintenance_only')
        with patch.object(m.product,'BASE',self.base),patch.object(m.product,'DELIVERY',self.candidate):
            with self.assertRaisesRegex(ValueError,'new product code required'):m.product.verify()
    def test_manifest_identity_and_modified_assertions_fail_closed(self):
        with patch.object(m.subprocess,'run',return_value=Mock(returncode=0)):
            self.expected='b'*64
            with self.assertRaises(ValueError):self.verify()
            (self.candidate/m.TEST).write_text(self.original.replace('assert True','assert False'))
            self.expected=self.freeze(self.candidate)
            with self.assertRaisesRegex(ValueError,'non-driver AST'):self.verify()
    def test_product_delta_and_baseline_edits_are_not_maintenance(self):
        for name in ('app.py','tests/test_old.py'):
            (self.candidate/name).write_text('changed')
            self.expected=self.freeze(self.candidate)
            with self.assertRaisesRegex(ValueError,'outside assigned test'):self.verify()
    def test_invalid_js_is_rejected_before_any_suite(self):
        with patch.object(m.subprocess,'run',return_value=Mock(returncode=1)):
            with self.assertRaisesRegex(ValueError,'syntax invalid'):self.verify()
