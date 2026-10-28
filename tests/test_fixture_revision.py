"""Structural admission is necessary, never sufficient, for fixture revision."""
import sys
from pathlib import Path
import unittest
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.test_revision import fixture_diff, fixture_snapshot_diff
from fabriquinha.artifacts import Store

OLD='''import unittest
class Capacity(AcceptanceTest):
    def helper(self):
        return self.new_context()
    def test_capacity(self):
        creator = 'unique'
        watcher = self.helper()
        self.assertEqual(watcher.count(creator), 1)
        self.assertEqual(watcher.errors, [])
'''
INSERT="        home = self.helper()\n        home.create(creator)\n"
NEW=OLD.replace('        watcher =',INSERT+'        watcher =')

class FixtureRevision(unittest.TestCase):
    def test_reports_added_setup_and_preserves_existing_statements(self):
        result=fixture_diff(OLD,NEW)
        self.assertEqual(list(result),['Capacity.test_capacity'])
        self.assertEqual(len(result['Capacity.test_capacity']),2)

    def test_rejects_removed_or_changed_assertion_and_discovery(self):
        for changed in (NEW.replace('        self.assertEqual(watcher.errors, [])\n',''),
                        NEW.replace('count(creator), 1','count(creator), 0'),
                        NEW.replace('test_capacity','disabled_capacity'),
                        NEW.replace('    def test_capacity','    @unittest.skip("fixture")\n    def test_capacity'),
                        NEW.replace('return self.new_context()','return None')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):fixture_diff(OLD,changed)

    def test_rejects_early_exit_control_flow_and_rebinding(self):
        for insertion in ('return','raise SystemExit()', 'creator = "different"',
                          'self.assertEqual = lambda *args: None', 'watcher = None',
                          'self.skipTest("fixture")', 'if True:\n            return',
                          'del creator', 'assert True', 'globals().clear()'):
            changed=OLD.replace('        watcher =','        '+insertion+'\n        watcher =')
            with self.subTest(insertion=insertion),self.assertRaises(ValueError):fixture_diff(OLD,changed)

    def test_noop_and_arbitrary_non_test_edits_are_not_revisions(self):
        for changed in (OLD,NEW+'\nunittest.TestCase.assertEqual = lambda *a: None\n',
                        NEW.replace('import unittest','import os')):
            with self.assertRaises(ValueError):fixture_diff(OLD,changed)

    def test_does_not_execute_candidate(self):
        changed=OLD.replace('        watcher =','        home = self.helper()\n        home.create(creator)\n        watcher =')
        self.assertTrue(fixture_diff(OLD,changed))

class SnapshotFixtureRevision(unittest.TestCase):
    def test_exact_paths_and_unchanged_product_manifest_and_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Store(root/'private');work=root/'work'
            (work/'tests').mkdir(parents=True)
            path='tests/acceptance_capacity.py'
            (work/path).write_text(OLD);(work/'app.py').write_text('product')
            (work/'tests/acceptance.json').write_text('{}')
            before=store.capture(work);(work/path).write_text(NEW);after=store.capture(work)
            self.assertEqual(list(fixture_snapshot_diff(store,before,after,[path],'tests')),[path])
            for paths in ([],[path,path],['tests/../tests/acceptance_capacity.py'],['app.py'],['tests/acceptance.json']):
                with self.subTest(paths=paths),self.assertRaises(ValueError):
                    fixture_snapshot_diff(store,before,after,paths,'tests')
            for unrelated in ('app.py','tests/acceptance.json','tests/new.py'):
                target=work/unrelated;old=target.read_bytes() if target.exists() else None
                target.write_text('changed')
                with self.subTest(unrelated=unrelated),self.assertRaises(ValueError):
                    fixture_snapshot_diff(store,before,store.capture(work),[path],'tests')
                if old is None:target.unlink()
                else:target.write_bytes(old)
            self.assertEqual((store.tree(before)/path).read_text(),OLD)

if __name__=='__main__':unittest.main()
