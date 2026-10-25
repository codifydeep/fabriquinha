"""Artifact and project boundaries; runs without Docker, Hermes or a model."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fabriquinha.artifacts import Store, protected_unchanged, digest
from fabriquinha.config import Project,execution_context


def configuration():
    return dict(version=1, namespace='delivery-kit-hermes-flow',
                repository='https://github.com/example/product', branch='release/demo',
                validation_image='sha256:' + 'a' * 64, tests_dir='tests',
                reviewers={'backend': 'lead', 'lead': 'cto'}, qualification=True)


class ProjectBoundaries(unittest.TestCase):
    def test_unknown_or_unbounded_configuration_is_rejected(self):
        for update in ({'max_workers': 3}, {'tests_dir': '../tests'},
                       {'validation_image': 'python:latest'}, {'shell': 'anything'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                Project.parse({**configuration(), **update})

    def test_self_review_is_rejected(self):
        with self.assertRaises(ValueError):
            Project.parse({**configuration(), 'reviewers': {'backend': 'backend'}})

    def test_ordered_substitutes_are_explicit_independent_and_immutable(self):
        source = {**configuration(), 'reviewers': {'backend': ['lead', 'cto']}}
        project = Project.parse(source)
        source['reviewers']['backend'].append('backend')
        self.assertEqual(project.reviewers_for('backend'), ('lead', 'cto'))
        self.assertEqual(project.reviewer('backend', exclude=('lead',)), 'cto')
        with self.assertRaises(ValueError):
            project.reviewer('backend', exclude=('lead', 'cto'))
        for candidates in ([], ['lead', 'lead'], ['backend', 'lead'], ['lead', None]):
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                Project.parse({**configuration(), 'reviewers': {'backend': candidates}})

    def test_review_matrix_is_immutable_and_fixture_cannot_become_production(self):
        source = configuration()
        project = Project.parse(source)
        source['reviewers']['backend'] = 'backend'
        self.assertEqual(project.reviewer('backend'), 'lead')
        with self.assertRaises(TypeError):
            project.reviewers['backend'] = 'backend'
        real = Project.parse({**configuration(), 'qualification': False})
        self.assertNotEqual(real.fingerprint(), project.fingerprint())

    def test_repository_identity_and_explicit_qualification(self):
        config = Project.parse(configuration())
        self.assertEqual(config.reviewer('backend'), 'lead')
        self.assertTrue(config.qualification)
        with self.assertRaises(ValueError):
            Project.parse({**configuration(), 'qualification': 'false'})

    def test_browser_toolchain_is_explicit_without_changing_old_project_identity(self):
        old={k:v for k,v in configuration().items() if k!='version'}
        old.update(max_workers=2,timeout_seconds=120)
        self.assertEqual(Project.parse(configuration()).fingerprint(),digest(old))
        browser=Project.parse({**configuration(),'browser_image':'sha256:'+'b'*64})
        self.assertNotEqual(browser.fingerprint(),digest(old))
        with self.assertRaises(ValueError):Project.parse({**configuration(),'browser_image':'browser:latest'})

    def test_browser_tdd_is_explicit_and_does_not_claim_unavailable_tools(self):
        old=Project.parse(configuration());new=Project.parse({**configuration(),'browser_tdd':True})
        self.assertNotEqual(old.fingerprint(),new.fingerprint())
        self.assertEqual(execution_context(old)['test_tooling']['available'],['unittest'])
        self.assertIn('playwright.sync_api',execution_context(new)['test_tooling']['available'])
        self.assertIn('assertion',execution_context(new)['test_tooling']['contract'])
        for value in ('true',1,[]):
            with self.assertRaises(ValueError):Project.parse({**configuration(),'browser_tdd':value})


class ArtifactBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'workspace'
        self.source.mkdir()
        (self.source / 'service.py').write_text('VALUE = 1\n')
        (self.source / 'tests').mkdir()
        (self.source / 'tests/test_service.py').write_text('test contract\n')
        self.store = Store(self.root / 'private')

    def test_snapshot_does_not_change_when_author_changes_workspace(self):
        snapshot = self.store.capture(self.source)
        (self.source / 'service.py').write_text('VALUE = 2\n')
        self.assertEqual((self.store.tree(snapshot) / 'service.py').read_text(), 'VALUE = 1\n')
        self.assertNotEqual(snapshot, self.store.capture(self.source))

    def test_symlink_escape_is_rejected(self):
        (self.source / 'escape').symlink_to(self.root)
        with self.assertRaises(ValueError):
            self.store.capture(self.source)

    def test_receipt_is_content_bound_and_not_a_caller_boolean(self):
        receipt = self.store.record('test', dict(task='t_1', run=1), dict(value='fact'))
        self.assertEqual(self.store.receipt(receipt)['payload']['value'], 'fact')
        path = self.store.root / 'receipts' / (receipt + '.json')
        path.write_text(json.dumps(dict(passed=True)))
        with self.assertRaises(ValueError):
            self.store.receipt(receipt)

    def test_modified_snapshot_is_rejected_on_read(self):
        snapshot = self.store.capture(self.source)
        tree = self.store.tree(snapshot)
        target = tree / 'service.py'
        target.chmod(0o644)
        target.write_text('changed\n')
        with self.assertRaises(ValueError):
            self.store.tree(snapshot)

    def test_existing_tests_and_discovery_are_protected(self):
        before = self.store.capture(self.source)
        (self.source / 'tests/test_service.py').write_text('weaker test\n')
        after = self.store.capture(self.source)
        with self.assertRaises(ValueError):
            protected_unchanged(self.store.manifest(before), self.store.manifest(after),
                                prefixes=('tests/',))

    def test_product_change_does_not_invalidate_unchanged_tests(self):
        before = self.store.capture(self.source)
        (self.source / 'service.py').write_text('VALUE = 2\n')
        after = self.store.capture(self.source)
        protected_unchanged(self.store.manifest(before), self.store.manifest(after), prefixes=('tests/',))

    def test_checkout_does_not_reset_existing_author_work(self):
        snapshot = self.store.capture(self.source)
        with self.assertRaises(ValueError):
            self.store.checkout(snapshot, self.source)
        self.assertEqual((self.source/'service.py').read_text(), 'VALUE = 1\n')


if __name__ == '__main__':
    unittest.main()
