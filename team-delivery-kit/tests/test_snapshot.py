import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('snapshot_copy', Path(__file__).parents[1] / 'broker/snapshot_copy.py')
snapshot_copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_copy)


class SnapshotTests(unittest.TestCase):
    def test_copies_exact_files_with_hash_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            target.mkdir()
            for name in snapshot_copy.FILES:
                (source / name).write_text(name)
            (source / 'unapproved.txt').write_text('ignored')
            with patch.object(snapshot_copy, 'SOURCE', source), patch.object(snapshot_copy, 'DESTINATION', target):
                snapshot_copy.main()
            self.assertEqual(sorted(p.name for p in target.iterdir()),
                             ['AGENTS.md', 'calc.py', 'manifest.json', 'test_calc.py'])
            manifest = json.loads((target / 'manifest.json').read_text())
            self.assertEqual(set(manifest['files']), set(snapshot_copy.FILES))
            self.assertEqual((target / 'calc.py').read_text(), 'calc.py')
            with patch.object(snapshot_copy, 'SOURCE', source), patch.object(snapshot_copy, 'DESTINATION', target):
                with self.assertRaises(ValueError):
                    snapshot_copy.main()

    def test_refuses_symlink_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            target.mkdir()
            for name in snapshot_copy.FILES:
                (source / name).write_text(name)
            (source / 'calc.py').unlink()
            (source / 'calc.py').symlink_to(source / 'test_calc.py')
            with patch.object(snapshot_copy, 'SOURCE', source), patch.object(snapshot_copy, 'DESTINATION', target):
                with self.assertRaises(ValueError):
                    snapshot_copy.main()
