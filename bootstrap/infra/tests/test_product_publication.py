import unittest
import hashlib
from product_publication import verify_publication
from product_node_ci import validate_files

class PublicationTests(unittest.TestCase):
    def test_exact_snapshot_is_not_pr_approval(self):
        result=verify_publication({'revision':'r','files':{'src/app.mjs':'source'}},{'adapter-node/src/app.mjs':'source'})
        self.assertTrue(result['snapshot_verified']);self.assertFalse(result['pr_approved'])
    def test_change_or_extra_workflow_rejected(self):
        packet={'revision':'r','files':{'src/app.mjs':'source'}}
        for files in ({},{'adapter-node/src/app.mjs':'changed'},{'adapter-node/src/app.mjs':'source','.github/workflows/x.yml':'x'}):
            with self.assertRaises(PermissionError):verify_publication(packet,files)

    def test_ci_rejects_replaced_test_bytes(self):
        files={'adapter-node/tests/example.test.mjs':b'assertion'}
        expected={n:hashlib.sha256(v).hexdigest() for n,v in files.items()}
        validate_files(expected,files)
        with self.assertRaises(PermissionError):validate_files(expected,{'adapter-node/tests/example.test.mjs':b'skip'})
