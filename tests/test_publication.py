"""Publication uses real private Git, fake GitHub transport and no model/token."""
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked, Pending
from fabriquinha.publication import GitHub, Publication, Repository
from test_delivery_core import configuration
from fixtures.github_transport import FakeGitHub


def git(folder, *args, data=None):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(folder), *args],
        input=data, stderr=subprocess.PIPE).decode().strip()


class PublicationFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        remote = self.root/'remote.git'
        remote.mkdir()
        git(remote, 'init', '--bare', '--initial-branch=main')
        seed = self.root/'seed'; seed.mkdir()
        git(seed, 'init', '--initial-branch=main')
        (seed/'app.py').write_text('VALUE = 1\n')
        git(seed, 'add', 'app.py')
        git(seed, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-m', 'Initial fixture')
        git(seed, 'remote', 'add', 'origin', str(remote))
        git(seed, 'push', 'origin', 'HEAD:refs/heads/release/demo')
        self.project = Project.parse(configuration())
        self.store = Store(self.root/'private')
        source = self.root/'candidate'; source.mkdir()
        (source/'app.py').write_text('VALUE = 2\n')
        self.snapshot = self.store.capture(source)
        self.review_run = Run('implementation', 2, 'lead', 'implementation', True,
                              'backend', 'v1', 'contract')
        red = self.store.record('red', {}, dict(red_job='fixture-red-job',baseline_job='fixture-baseline-job',
                                               new_cases=['test_behavior'],baseline=self.store.capture(seed)))
        frozen = self.store.record('tests_frozen', {}, dict(red=red))
        green = self.store.record('green', {}, dict(cases=['test_behavior'], snapshot=self.snapshot,
                                                   freeze=frozen,job='fixture-green-job'))
        controls = self.store.record('controls', {}, dict(green=green,jobs=['fixture-negative-job']))
        self.review = self.store.record('delivery_review', self.review_run.binding(),
            dict(project=self.project.fingerprint(), qualification=True, snapshot=self.snapshot,
                 verdict=dict(decision='approve', reason='Fixture decision', findings=[]),
                 green=green,controls=controls,validation_job='fixture-review-job',
                 merge_authorized=False, delivery_approval=False))
        self.run = Run('integration', 3, 'lead', 'integration', False, 'lead', 'v1', 'contract')
        self.board = SimpleNamespace(ensure=lambda run: None, input=lambda run,name:self.review,
                                     require_parent=lambda run,parent:None)
        self.repo = Repository(self.project, self.store, remote=remote)
        self.github = FakeGitHub(self.repo)
        self.publisher = Publication(self.project, self.store, self.board, self.repo, self.github)

    def publish(self):
        return self.publisher.publish(self.run, self.review)

    def test_exact_snapshot_is_integrated_and_merge_sha_is_not_pr_head(self):
        key = self.publish()
        value = self.store.receipt(key, kind='publication')['payload']
        self.assertNotEqual(value['head_sha'], value['merge_sha'])
        self.assertEqual(self.repo.snapshot(value['merge_sha']), self.snapshot)
        self.assertEqual(self.github.calls, dict(create=1, merge=1))
        self.assertFalse(value['delivery_approval'])
        self.assertTrue(value['qualification'])
        self.assertEqual(self.publish(), key)
        self.assertEqual(self.github.calls, dict(create=1, merge=1))

    def test_lost_create_ack_observes_same_pr(self):
        self.github.lose_create = True
        with self.assertRaises(Pending):
            self.publish()
        self.publish()
        self.assertEqual(self.github.calls['create'], 1)

    def test_lost_merge_ack_observes_same_merge(self):
        self.github.lose_merge = True
        with self.assertRaises(Pending):
            self.publish()
        self.publish()
        self.assertEqual(self.github.calls['merge'], 1)

    def test_new_claim_resumes_same_pr_without_repeating_accepted_effects(self):
        self.github.lose_create = True
        with self.assertRaises(Pending):
            self.publish()
        first_run = self.run
        self.run = replace(first_run, number=first_run.number+1)
        result = self.store.receipt(self.publish(), kind='publication')
        self.assertEqual(result['binding'], self.run.binding())
        self.assertEqual(result['payload']['origin'], first_run.binding())
        self.assertEqual(self.github.calls, dict(create=1,merge=1))
        self.assertEqual(self.repo.git('branch', '--list', 'feat/*').decode().count('feat/'), 1)

    def test_new_claim_does_not_reset_pr_or_merge_ci_deadline(self):
        first_run = self.run
        self.github.ok = False
        with patch('fabriquinha.publication.time.time', return_value=100):
            with self.assertRaises(Pending): self.publish()
        self.run = replace(first_run, number=first_run.number+1)
        with patch('fabriquinha.publication.time.time', return_value=1001):
            with self.assertRaises(EffectBlocked): self.publish()
        self.github.ok = True
        publication = self.publish()
        quality = SimpleNamespace(observe=lambda *args:None)
        self.github.ok = False
        with patch('fabriquinha.publication.time.time', return_value=2000):
            with self.assertRaises(Pending):
                self.publisher.validate_integrated(self.run,publication,quality)
        self.run = replace(first_run, number=first_run.number+2)
        self.github.ok = True
        publication = self.publish()
        self.github.ok = False
        with patch('fabriquinha.publication.time.time', return_value=2901):
            with self.assertRaises(EffectBlocked):
                self.publisher.validate_integrated(self.run,publication,quality)
        self.assertEqual(self.github.calls, dict(create=1,merge=1))

    def test_pending_ci_never_merges(self):
        self.github.ok = False
        with self.assertRaises(Pending):
            self.publish()
        self.assertEqual(self.github.calls['merge'], 0)

    def test_unapproved_review_never_pushes_or_creates_pr(self):
        old = self.store.receipt(self.review)
        old['payload']['verdict']['decision'] = 'changes'
        self.review = self.store.record('delivery_review', old['binding'], old['payload'])
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.github.calls, dict(create=0, merge=0))

    def test_old_review_input_is_rejected(self):
        self.board.input = lambda run,name:'another-delivery'
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.github.calls, dict(create=0, merge=0))

    def test_unqualified_local_remote_override_is_rejected(self):
        real = Project.parse({**configuration(), 'qualification':False})
        with self.assertRaises(ValueError):
            Repository(real, self.store, remote=self.root/'remote.git')

    def test_qualification_cannot_use_real_github_write(self):
        github = GitHub(self.project, 'lead')
        with self.assertRaises(ValueError):
            github.create('fixture', 'title', 'body')

    def test_integrated_commit_gets_its_own_ci_and_complete_suite(self):
        publication = self.publish()
        observed = []
        def observe(run, snapshot, phase):
            observed.append((snapshot,phase))
            return 'fixture-job', dict(failures=[], cases=['test_behavior'])
        key = self.publisher.validate_integrated(self.run, publication, SimpleNamespace(observe=observe))
        result = self.store.receipt(key, kind='integrated')['payload']
        self.assertEqual(result['commit'], self.repo.remote_head(self.project.branch))
        self.assertEqual(observed, [(self.snapshot,'integrated')])
        self.assertFalse(result['delivery_approval'])

    def test_ci_deadline_survives_repeated_observation(self):
        self.github.ok = False
        with patch('fabriquinha.publication.time.time', return_value=100):
            with self.assertRaises(Pending):
                self.publish()
        with patch('fabriquinha.publication.time.time', return_value=1001):
            with self.assertRaises(EffectBlocked):
                self.publish()
        self.assertEqual(self.github.calls, dict(create=1,merge=0))

    def test_unrelated_completed_card_cannot_authorize_publication(self):
        def reject(run, parent):
            raise ValueError('not a dependency')
        self.board.require_parent = reject
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.github.calls, dict(create=0,merge=0))

    def test_wrong_commit_ci_never_authorizes_integrated_result(self):
        publication = self.publish()
        self.github.accept = lambda url,sha=None:dict(ok=True, head_sha='f'*40, required=['fixture'])
        with self.assertRaises(EffectBlocked):
            self.publisher.validate_integrated(self.run, publication, SimpleNamespace(observe=lambda *a:None))

    def test_base_advance_is_not_merged_without_rebase_and_review(self):
        original = self.github.accept
        def advance(url, sha=None):
            result = original(url,sha)
            self.repo.git('push','origin',self.github.pr['headRefOid']+':refs/heads/'+self.project.branch)
            return result
        self.github.accept = advance
        with self.assertRaises(EffectBlocked):
            self.publish()
        self.assertEqual(self.github.calls['merge'], 0)

    def test_newly_merged_tests_cannot_be_deleted_by_an_older_author_snapshot(self):
        newer=self.root/'new-base';newer.mkdir()
        (newer/'app.py').write_text('VALUE = 1\n')
        (newer/'tests').mkdir()
        (newer/'tests/test_existing.py').write_text('import unittest, app\nclass Existing(unittest.TestCase):\n def test_contract(self): self.assertIsInstance(app.VALUE,int)\n')
        new_snapshot=self.store.capture(newer)
        commit=self.repo.propose(new_snapshot,self.repo.base(),'fixture-prior-delivery','lead')
        self.repo.git('push','origin',commit+':refs/heads/'+self.project.branch)
        with self.assertRaises(EffectBlocked):self.publish()
        self.assertEqual(self.github.calls,dict(create=0,merge=0))

    def test_merge_content_change_requires_another_independent_review(self):
        other = self.root/'other'; other.mkdir()
        (other/'app.py').write_text('VALUE = "unreviewed merge"\n')
        snapshot = self.store.capture(other)
        proposal = self.repo.propose(snapshot,self.repo.base(),'fixture-other-tree','lead')
        self.github.tree_override = self.repo.git('rev-parse',proposal+'^{tree}').decode().strip()
        publication = self.publish()
        with self.assertRaises(EffectBlocked):
            self.publisher.validate_integrated(self.run,publication,SimpleNamespace(observe=lambda *args:None))

    def test_merge_ci_wait_does_not_get_a_new_deadline_on_restart(self):
        publication = self.publish()
        self.github.ok = False
        quality = SimpleNamespace(observe=lambda *args:None)
        with patch('fabriquinha.publication.time.time',return_value=100):
            with self.assertRaises(Pending):
                self.publisher.validate_integrated(self.run,publication,quality)
        with patch('fabriquinha.publication.time.time',return_value=1001):
            with self.assertRaises(EffectBlocked):
                self.publisher.validate_integrated(self.run,publication,quality)


if __name__ == '__main__':
    unittest.main()
