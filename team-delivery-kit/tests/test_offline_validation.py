from pathlib import Path
import tempfile
import unittest

from offline_validation import copy_sources, PUBLIC_EVIDENCE


class OfflineValidationTests(unittest.TestCase):
    def fixture(self, root):
        for name in ('broker', 'tests', 'projects', 'deploy', 'evaluation', '.local'):
            (root / name).mkdir()
        (root / PUBLIC_EVIDENCE[0]).write_text('{"status":"passed"}')
        (root / 'evaluation/private.json').write_text('not public')
        (root / '.local/secret').write_text('not public')

    def test_required_evidence_is_copied_without_private_state(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            root, target = Path(a), Path(b)
            self.fixture(root)
            copy_sources(root, target)
            self.assertEqual((target / PUBLIC_EVIDENCE[0]).read_bytes(),
                             (root / PUBLIC_EVIDENCE[0]).read_bytes())
            self.assertFalse((target / 'evaluation/private.json').exists())
            self.assertFalse((target / '.local').exists())

    def test_missing_or_symlinked_evidence_fails_closed(self):
        for symlink in (False, True):
            with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                root, target = Path(a), Path(b)
                self.fixture(root)
                evidence = root / PUBLIC_EVIDENCE[0]
                evidence.unlink()
                if symlink:
                    evidence.symlink_to(root / 'evaluation/private.json')
                with self.assertRaises(ValueError):
                    copy_sources(root, target)
