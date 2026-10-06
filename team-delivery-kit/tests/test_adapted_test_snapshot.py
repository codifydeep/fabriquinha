import hashlib
import json
import unittest

import test_test_first_protocol as fixtures
from test_framework_mark_diagnosis import SOURCE
from broker.adapted_test_snapshot import materialize
from broker.framework_mark_diagnosis import adapt_required_node


class AdaptedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TestFirstProtocolTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base, self.source, self.dest = self.fixture.base, self.fixture.work, self.fixture.red
        (self.source/'tests/test_new.py').write_bytes(SOURCE)
        files = {str(p.relative_to(self.source)): {
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
            for p in self.source.rglob('*') if p.is_file()}
        (self.source/'manifest.json').write_text(json.dumps({'files': files}))
        candidate, _ = adapt_required_node(SOURCE, hashlib.sha256(SOURCE).hexdigest())
        self.selection = dict(revision_id='11111111-1111-4111-8111-111111111111',
            path='tests/test_new.py', original_sha256=hashlib.sha256(SOURCE).hexdigest(),
            expected_candidate_sha256=hashlib.sha256(candidate).hexdigest(),
            base_manifest_sha256=hashlib.sha256((self.base/'manifest.json').read_bytes()).hexdigest(),
            source_manifest_sha256=hashlib.sha256((self.source/'manifest.json').read_bytes()).hexdigest())

    def freeze(self):
        return materialize(self.base, self.source, self.dest, self.selection)

    def test_new_revision_preserves_original_baseline_and_no_red(self):
        before = (self.source/'tests/test_new.py').read_bytes()
        receipt = self.freeze()
        self.assertEqual((self.source/'tests/test_new.py').read_bytes(), before)
        self.assertEqual((self.dest/'app.py').read_bytes(), self.fixture.old['app.py'])
        self.assertEqual((self.dest/'tests/test_new.py').stat().st_mode & 0o777, 0o400)
        self.assertFalse(receipt['delivery_approval'])
        self.assertFalse(receipt['red_evidence'])
        self.assertEqual(receipt['revision_id'], self.selection['revision_id'])

    def test_repeated_materialization_is_identical(self):
        self.assertEqual(self.freeze(), self.freeze())

    def test_changed_source_baseline_is_rejected_before_write(self):
        (self.source/'app.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse(list(self.dest.iterdir()))

    def test_wrong_candidate_hash_is_rejected_before_write(self):
        self.selection['expected_candidate_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse(list(self.dest.iterdir()))

    def test_partial_snapshot_resumes_but_drift_is_rejected(self):
        (self.dest/'app.py').write_bytes(self.fixture.old['app.py'])
        receipt = self.freeze()
        (self.dest/'app.py').chmod(0o600)
        (self.dest/'app.py').write_bytes(b'drift')
        with self.assertRaises(ValueError):
            self.freeze()
        self.assertFalse(receipt['red_evidence'])

    def test_destination_symlink_is_rejected(self):
        (self.dest/'tests').symlink_to(self.source/'tests', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.freeze()
