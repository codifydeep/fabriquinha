import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from product_test_sandbox import manifest,command

class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'test.mjs').write_text('test fixture')
    def test_fixed_readonly_operation(self):
        cmd=command(self.root,'sha256:'+'a'*64,'probe')
        for flag in ('--network=none','--read-only','--cap-drop=ALL','--user=10000:10000'):self.assertIn(flag,cmd)
        self.assertEqual(cmd[-1],'--test');self.assertFalse(any('docker.sock' in x for x in cmd))
    def test_symlink_denied(self):
        (self.root/'link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):manifest(self.root)
    def test_secret_file_denied(self):
        (self.root/'.env').write_text('fixture')
        with self.assertRaises(ValueError):manifest(self.root)
    def test_tag_denied(self):
        with self.assertRaises(ValueError):command(self.root,'node:latest','probe')
    def test_identity_denied(self):
        with self.assertRaises(ValueError):command(self.root,'sha256:'+'a'*64,'../other')
