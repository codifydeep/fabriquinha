import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_merge import validate_context, reject_governance_files

class MergeIdentityTests(unittest.TestCase):
    def test_normal_product_files_allowed(self):
        reject_governance_files([dict(path='src/game.py'),dict(path='tests/test_game.py')],2)

    def test_ci_scripts_and_workflows_require_governance_route(self):
        for path in ('scripts/ci/run-project-checks.sh','scripts/ci/check-planning-snapshots.py',
                     'scripts/ci/check-docker-naming.sh','.github/workflows/new.yml'):
            with self.assertRaises(ValueError): reject_governance_files([dict(path=path)],1)

    def test_truncated_file_listing_rejected(self):
        with self.assertRaises(ValueError): reject_governance_files([dict(path='src/a.py')],2)

    def test_renaming_protected_script_is_not_an_escape(self):
        with self.assertRaises(ValueError):
            reject_governance_files([dict(filename='src/check.py',previous_filename='scripts/ci/check-planning-snapshots.py')],1)
    def setUp(self):
        self.task = dict(status='running',current_run_id=9,assignee='cto')
        self.handoff = dict(implementer='techlead',reviewer='cto')
        self.claim = dict(source_status='review')

    def test_valid_review_context(self):
        validate_context(self.task,self.handoff,self.claim,'cto','9')

    def test_stale_or_implementation_run_rejected(self):
        with self.assertRaises(ValueError): validate_context(self.task,self.handoff,self.claim,'cto','8')
        with self.assertRaises(ValueError): validate_context(self.task,self.handoff,{},'cto','9')

    def test_wrong_actor_or_self_review_rejected(self):
        with self.assertRaises(ValueError): validate_context(self.task,self.handoff,self.claim,'techlead','9')
        self.handoff['implementer']='cto'
        with self.assertRaises(ValueError): validate_context(self.task,self.handoff,self.claim,'cto','9')
