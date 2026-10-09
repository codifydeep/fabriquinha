import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from broker import candidate_inventory as inventory
from test_portable_contract import contract


class CandidateInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.base=root/'base';self.delivery=root/'delivery'
        self.base.mkdir();self.delivery.mkdir()
        self.spec=contract()
        ui=['app/static/app.js','app/static/index.html','app/static/style.css']
        self.spec['files']+=ui;self.spec['editable_files']+=ui
        encoded=json.dumps(self.spec).encode()
        contents={'AGENTS.md':b'policy','app.py':b'original',
            'tests/test_old.py':b'def test_old(): assert True',
            **{name:b'original UI' for name in ui},'contract.json':encoded}
        for name,data in contents.items():
            target=self.base/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        (self.base/'manifest.json').write_text(json.dumps({'base_sha':'a'*40,
            'files':{name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}}))
        contents.pop('contract.json');contents['app/static/app.js']=b'actual partial product'
        contents['tests/test_new.py']=b'def test_new(): assert False'
        for name,data in contents.items():
            target=self.delivery/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        (self.delivery/'manifest.json').write_text(json.dumps({'files':{
            name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in contents.items()}}))
        for attr,path in [('BASE',self.base),('DELIVERY',self.delivery)]:
            patcher=patch.object(inventory.structural,attr,path);patcher.start();self.addCleanup(patcher.stop)

    def test_frontend_inventory_preserves_legacy_diagnostics_and_test_hashes(self):
        proof=inventory.inventory()
        self.assertEqual(set(proof['product_file_sha256']),set(self.spec['editable_files'])-set(self.spec['test_files']))
        self.assertEqual(set(proof['diagnostic_file_sha256']),{'app.py'})
        self.assertEqual(proof['product_file_sha256']['app/static/app.js'],hashlib.sha256(b'actual partial product').hexdigest())
        self.assertNotIn('AGENTS.md',proof['product_file_sha256'])
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['tests_executed'])
        self.assertTrue(proof['baseline_tests_intact'])
        self.assertEqual(set(proof['baseline_test_sha256']),{'tests/test_old.py'})
        self.assertEqual(set(proof['new_test_sha256']),{'tests/test_new.py'})

    def test_tampered_ui_or_baseline_tests_cannot_produce_inventory(self):
        (self.delivery/'app/static/app.js').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'frozen hash mismatch'):inventory.inventory()
        (self.delivery/'app/static/app.js').write_bytes(b'actual partial product')
        (self.delivery/'tests/test_old.py').write_bytes(b'weakened test')
        with self.assertRaises(ValueError):inventory.inventory()

    def test_manifest_change_after_validation_is_not_a_new_receipt(self):
        proof=inventory.structural.verify()
        (self.delivery/'manifest.json').write_text('{}')
        with patch.object(inventory.structural,'verify',return_value=proof):
            with self.assertRaisesRegex(ValueError,'manifest changed'):inventory.inventory()
