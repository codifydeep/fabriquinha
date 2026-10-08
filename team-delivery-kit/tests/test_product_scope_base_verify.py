import hashlib
import json
import unittest
import test_product_scope_materialize as fixtures
from broker.product_scope_base_verify import verify


class ProductScopeBaseVerifyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeMaterializeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.receipt=self.f.run_materialize()

    def call(self):
        return verify(self.f.base,self.f.target,self.f.state,hashlib.sha256(self.f.encoded).hexdigest(),self.receipt)

    def test_readonly_qualification_binds_exact_original_base_and_preserved_tests(self):
        result=self.call()
        self.assertEqual(result['contract_sha256'],self.receipt['contract_sha256'])
        self.assertEqual(result['manifest_sha256'],self.receipt['manifest_sha256'])
        self.assertFalse(result['delivery_approval']);self.assertFalse(result['write_grant_issued'])
        self.assertEqual(result['frozen_test_sha256'],self.f.state['context']['frozen_test_sha256'])

    def test_corrupted_code_or_tests_cannot_be_reclassified_with_a_new_manifest(self):
        for name in ('app/db.py','tests/test_old.py'):
            with self.subTest(name=name):
                path=self.f.target/name;original=path.read_bytes();path.chmod(0o644);path.write_bytes(b'changed')
                with self.assertRaises(ValueError):self.call()
                path.write_bytes(original)

    def test_missing_file_extra_file_and_symlink_never_qualify(self):
        extra=self.f.target/'extra.txt';extra.write_text('extra')
        with self.assertRaises(ValueError):self.call()
        extra.unlink()
        path=self.f.target/'app/db.py';path.unlink()
        with self.assertRaises(ValueError):self.call()
        path.symlink_to(self.f.base/'app/db.py')
        with self.assertRaises(ValueError):self.call()
