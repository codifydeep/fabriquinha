import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from broker.worker_interruption_snapshot import preserve


class WorkerInterruptionSnapshotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.base, self.work, self.snapshot = (root / n for n in ('base', 'work', 'snapshot'))
        for p in (self.base, self.work, self.snapshot): p.mkdir()
        contract = json.loads((Path(__file__).parents[1] / 'projects/descartavel2-workerrec-1.contract.json').read_text())
        self.test = 'tests/test_worker_ping.py'
        self.original = next(n for n in contract['files'] if n not in contract['editable_files'])
        p = self.work / self.original; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'baseline')
        p = self.work / self.test; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'frozen test')
        (self.base / 'contract.json').write_text(json.dumps(contract))
        (self.base / 'manifest.json').write_text(json.dumps(dict(files={self.original: hashlib.sha256(b'baseline').hexdigest()})))
        self.hashes = {self.test: hashlib.sha256(b'frozen test').hexdigest()}

    def test_preserves_frozen_tests_without_recapturing_red_or_approval(self):
        receipt = preserve(self.base, self.work, self.snapshot, self.hashes)
        self.assertTrue(receipt['frozen_tests_unchanged'])
        self.assertFalse(receipt['red_verified']); self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(receipt['frozen_test_hashes'], self.hashes)
        self.assertEqual(preserve(self.base, self.work, self.snapshot, self.hashes), receipt)
        self.assertEqual((self.snapshot / self.test).stat().st_mode & 0o777, 0o400)

    def test_changed_frozen_test_or_invalid_identity_rejected_before_snapshot(self):
        for hashes in ({self.test: '0'*64}, {'../secret': 'a'*64}, {}, {self.original: 'a'*64}):
            with self.subTest(hashes=hashes):
                with self.assertRaises(ValueError): preserve(self.base, self.work, self.snapshot, hashes)
                self.assertEqual(list(self.snapshot.iterdir()), [])

    def test_existing_snapshot_cannot_be_overwritten(self):
        preserve(self.base, self.work, self.snapshot, self.hashes)
        p = self.snapshot / self.test; p.chmod(0o600); p.write_bytes(b'changed')
        with self.assertRaises(ValueError): preserve(self.base, self.work, self.snapshot, self.hashes)
