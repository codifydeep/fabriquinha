import hashlib,json,unittest
from broker.normalize_new_test import normalize
import test_test_first_protocol as protocol_fixture


class NormalizeNewTestTests(unittest.TestCase):
    def setUp(self):
        fixture=protocol_fixture.TestFirstProtocolTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.base,self.work,self.archive=fixture.base,fixture.work,fixture.red
        self.path=self.work/'tests/test_new.py'
        self.original=fixture.new+b'#'+b'x'*34000+b'\n'
        self.path.write_bytes(self.original)
        self.selection={'path':'tests/test_new.py','sha256':hashlib.sha256(self.original).hexdigest()}

    def test_preserves_original_and_ast_then_resumes_without_another_edit(self):
        result=normalize(self.base,self.work,self.archive,self.selection)
        self.assertTrue(result['identical_ast']);self.assertLessEqual(result['formatted_bytes'],32768)
        self.assertEqual((self.archive/'original.py').read_bytes(),self.original)
        current=self.path.read_bytes()
        self.assertEqual(normalize(self.base,self.work,self.archive,self.selection),result)
        self.assertEqual(self.path.read_bytes(),current)

    def test_wrong_hash_or_baseline_file_cannot_be_changed(self):
        with self.assertRaisesRegex(ValueError,'source drift'):
            normalize(self.base,self.work,self.archive,{**self.selection,'sha256':'0'*64})
        self.assertEqual(self.path.read_bytes(),self.original)
        with self.assertRaisesRegex(ValueError,'NEW Python'):
            normalize(self.base,self.work,self.archive,{**self.selection,'path':'tests/test_old.py'})

    def test_oversized_result_or_changed_baseline_fails_before_backup(self):
        self.path.write_bytes(b'PAYLOAD='+repr('x'*34000).encode()+b'\n')
        selection={**self.selection,'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}
        with self.assertRaisesRegex(ValueError,'AST and byte gate'):
            normalize(self.base,self.work,self.archive,selection)
        self.assertFalse((self.archive/'original.py').exists())
        (self.work/'app.py').write_text('changed\n')
        with self.assertRaisesRegex(ValueError,'baseline changed'):
            normalize(self.base,self.work,self.archive,selection)

    def test_restart_after_backup_before_workspace_write_and_drift_rejection(self):
        result=normalize(self.base,self.work,self.archive,self.selection)
        self.path.write_bytes(self.original)
        self.assertEqual(normalize(self.base,self.work,self.archive,self.selection),result)
        self.path.write_text('def test_new(): pass\n')
        with self.assertRaisesRegex(ValueError,'workspace drift'):
            normalize(self.base,self.work,self.archive,self.selection)
