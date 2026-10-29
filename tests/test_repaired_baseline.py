"""Legacy test correction preserves original product, inventory and configuration."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.test_revision import protect_repaired_baseline,repaired_baseline,verify_repaired_baseline


class RepairedBaseline(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.store=Store(root/'private');self.work=root/'work';self.work.mkdir()
        (self.work/'tests').mkdir()
        (self.work/'app.py').write_text('VERSION = 1\n')
        (self.work/'tests/acceptance_old.py').write_text('OLD = 1\n')
        (self.work/'tests/acceptance_other.py').write_text('OTHER = 1\n')
        (self.work/'pytest.ini').write_text('[pytest]\n')
        self.project=SimpleNamespace(tests_dir='tests');self.paths=['tests/acceptance_old.py']
        self.base=self.store.capture(self.work)
        (self.work/'tests/acceptance_old.py').write_text('OLD = 2\n')
        (self.work/'tests/acceptance_new.py').write_text('NEW = 1\n')
        self.candidate=self.store.capture(self.work)

    def test_projection_retains_original_product_and_original_inventory(self):
        protect_repaired_baseline(self.project,self.store,self.base,self.candidate,self.paths)
        corrected=repaired_baseline(self.store,self.base,self.candidate,self.paths)
        verify_repaired_baseline(self.store,self.base,self.candidate,self.paths,corrected)
        self.assertEqual(set(self.store.manifest(corrected)),set(self.store.manifest(self.base)))
        self.assertEqual((self.store.tree(self.base)/self.paths[0]).read_text(),'OLD = 1\n')
        self.assertEqual((self.store.tree(corrected)/self.paths[0]).read_text(),'OLD = 2\n')
        self.assertEqual((self.store.tree(corrected)/'app.py').read_text(),'VERSION = 1\n')

    def test_unscoped_regression_and_config_changes_remain_blocked(self):
        for path in ('tests/acceptance_other.py','pytest.ini'):
            target=self.work/path;before=target.read_text();target.write_text('CHANGED = 1\n')
            with self.subTest(path=path),self.assertRaises(ValueError):
                protect_repaired_baseline(self.project,self.store,self.base,self.store.capture(self.work),self.paths)
            target.write_text(before)

    def test_removal_of_even_authorized_test_is_blocked(self):
        (self.work/self.paths[0]).unlink()
        with self.assertRaises(ValueError):
            protect_repaired_baseline(self.project,self.store,self.base,self.store.capture(self.work),self.paths)

    def test_projected_baseline_cannot_include_new_product_or_test(self):
        with self.assertRaises(ValueError):
            verify_repaired_baseline(self.store,self.base,self.candidate,self.paths,self.candidate)
        (self.work/'app.py').write_text('VERSION = 2\n')
        with self.assertRaises(ValueError):
            verify_repaired_baseline(self.store,self.base,self.candidate,self.paths,self.store.capture(self.work))
