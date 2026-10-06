from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from delivery_receipts import EvidenceStore


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=EvidenceStore(self.root/'evidence','r2')
        self.work=self.root/'work'
        self.work.mkdir()
        (self.work/'test.log').write_text('3 tests passed\n')

    def test_evidence_survives_workspace_removal(self):
        blob=self.store.capture(self.work,'test.log')
        receipt=self.store.save({'kind':'qa','task':'t1','artifacts':[blob]})
        (self.work/'test.log').unlink()
        self.assertEqual(self.store.load(receipt)['artifacts'][0]['sha256'],blob['sha256'])

    def test_tampered_blob_is_rejected(self):
        blob=self.store.capture(self.work,'test.log')
        receipt=self.store.save({'kind':'qa','artifacts':[blob]})
        (self.store.root/'blobs'/blob['sha256']).write_text('tampered')
        with self.assertRaises(ValueError):
            self.store.load(receipt)

    def test_outside_path_and_symlink_are_rejected(self):
        (self.root/'outside').write_text('private')
        (self.work/'escape').symlink_to(self.root/'outside')
        for name in ('../outside','escape'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                self.store.capture(self.work,name)

    def test_receipt_is_content_addressed_and_attempt_scoped(self):
        one=self.store.save({'kind':'implementation','task':'t1'})
        self.assertEqual(one,self.store.save({'kind':'implementation','task':'t1'}))
        self.assertNotEqual(one,self.store.save({'kind':'implementation','task':'t2'}))
        self.assertEqual(self.store.load(one)['attempt'],'r2')

    def test_committed_bytes_are_archived_and_verified(self):
        artifact=self.store.capture_bytes('evidence/qa.log',b'passed\n')
        receipt=self.store.save({'kind':'homologation','artifacts':[artifact]})
        self.assertEqual(self.store.load(receipt)['artifacts'],[artifact])

    def test_raw_bytes_reject_unsafe_paths_and_empty_content(self):
        for name,data in [('../secret',b'x'),('/secret',b'x'),('log',b'')]:
            with self.subTest(name=name),self.assertRaises(ValueError):
                self.store.capture_bytes(name,data)
