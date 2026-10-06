import unittest
from product_manifest import manifest,verify
from product_workspace import digest
from product_policy import context

class ManifestTests(unittest.TestCase):
    def test_canonical_manifest_and_drift(self):
        c=dict(cards={'t':context('planning')},runtime_manifest_sha256=digest(manifest()))
        self.assertTrue(verify(c)['verified'])
        c['runtime_manifest_sha256']='x'
        with self.assertRaises(PermissionError):verify(c)
    def test_invalid_role_cannot_be_registered_as_routine(self):
        c=dict(cards={'t':dict(context('planning'),reviewer='backend_data')})
        with self.assertRaises(PermissionError):verify(c)
