"""Local CI binds real Git snapshots; execution is mocked in unit tests only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked
from fabriquinha.publication import LocalCI,Repository
from test_delivery_core import configuration
from test_publication import git


class LocalCIBoundaries(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        remote=self.root/'remote.git';remote.mkdir();git(remote,'init','--bare','--initial-branch=main')
        seed=self.root/'seed';seed.mkdir();git(seed,'init','--initial-branch=main')
        (seed/'tests').mkdir();(seed/'tests/test_existing.py').write_text('import unittest\n')
        (seed/'app.py').write_text('VALUE = 1\n');git(seed,'add','.')
        git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-m','CI infrastructure fixture')
        git(seed,'remote','add','origin',str(remote));git(seed,'push','origin','HEAD:refs/heads/release/demo')
        self.project=Project.parse(configuration());self.store=Store(self.root/'private')
        self.repo=Repository(self.project,self.store,remote=remote);self.base=self.repo.base()
        self.work=self.root/'candidate';self.store.checkout(self.repo.snapshot(self.base),self.work)
        (self.work/'app.py').write_text('VALUE = 2\n')
        self.runner=Mock();self.runner.run.side_effect=self.execute
        self.ci=LocalCI(self.project,self.store,self.repo,self.runner)
        self.report=dict(version=1,tests_run=1,cases=['test_existing.Case.test_value'],failures=[],errors=[],skips=[],expected_failures=[],unexpected_successes=[])
        self.exit=0;self.foreign=False

    def propose(self):
        snapshot=self.store.capture(self.work)
        head=self.repo.propose(snapshot,self.base,'ci/proposal','fixture');self.repo.push('ci/proposal',head)
        return head

    def execute(self,context,snapshot,phase):
        binding=context.binding();identity=dict(binding=binding,project=self.project.fingerprint(),snapshot=snapshot,
            phase=phase,image=self.project.validation_image)
        if self.foreign:identity['snapshot']='b'*64
        report=(dict(version=1,tests_run=1,cases=['test_existing.Case.test_value'],failures=[],errors=[],skips=[],expected_failures=[],unexpected_successes=[])
                if phase=='baseline' else self.report)
        return self.store.record('suite_job',binding,dict(identity=identity,exit_code=0 if phase=='baseline' else self.exit,report=report,
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))

    def test_proposal_is_exact_and_receipt_never_impersonates_a_native_run(self):
        head=self.propose();receipt=self.store.receipt(self.ci.validate(head,self.base,stage='proposal'),kind='ci_validation')
        self.assertEqual(receipt['payload']['conclusion'],'success');self.assertEqual(receipt['payload']['head'],head)
        self.assertEqual(receipt['binding']['scope'],'local_ci');self.assertNotIn('task',receipt['binding'])
        self.assertFalse(receipt['payload']['merge_authorized']);self.assertFalse(receipt['payload']['delivery_approval'])

    def test_failed_suite_produces_failure_not_a_success_receipt(self):
        head=self.propose();self.report['failures']=[dict(case=self.report['cases'][0])];self.exit=1
        receipt=self.store.receipt(self.ci.validate(head,self.base,stage='proposal'))
        self.assertEqual(receipt['payload']['conclusion'],'failure')

    def test_modified_existing_tests_are_rejected_before_job_execution(self):
        (self.work/'tests/test_existing.py').write_text('import unittest\n# changed old test\n')
        with self.assertRaisesRegex(ValueError,'protected baseline changed'):self.ci.validate(self.propose(),self.base,stage='proposal')
        self.runner.run.assert_not_called()

    def test_additive_feature_tests_pass_proposal_and_integrated_ci_without_a_correction(self):
        (self.work/'tests/test_new.py').write_text('import unittest\n')
        self.report['cases'].append('test_new.Case.test_new_behavior');self.report['tests_run']=2
        head=self.propose()
        proposal=self.store.receipt(self.ci.validate(head,self.base,stage='proposal'))['payload']
        self.assertEqual(proposal['conclusion'],'success');self.assertEqual(proposal['tests_run'],2)
        self.repo.push(self.project.branch,head)
        integrated=self.store.receipt(self.ci.validate(head,self.base,stage='integrated'))['payload']
        self.assertEqual(integrated['conclusion'],'success');self.assertEqual(integrated['snapshot'],proposal['snapshot'])
        self.assertFalse(integrated['delivery_approval'])

    def test_new_test_does_not_authorize_modifying_an_existing_test(self):
        (self.work/'tests/test_new.py').write_text('import unittest\n')
        (self.work/'tests/test_existing.py').write_text('import unittest\n# weakened\n')
        with self.assertRaisesRegex(ValueError,'protected baseline changed'):
            self.ci.validate(self.propose(),self.base,stage='proposal')
        self.runner.run.assert_not_called()

    def test_replacing_an_old_test_with_a_new_file_does_not_count_as_an_addition(self):
        (self.work/'tests/test_existing.py').unlink()
        (self.work/'tests/test_new.py').write_text('import unittest\n')
        with self.assertRaisesRegex(ValueError,'protected baseline changed'):
            self.ci.validate(self.propose(),self.base,stage='proposal')
        self.runner.run.assert_not_called()

    def test_skips_empty_or_foreign_job_cannot_pass(self):
        head=self.propose();original=json.loads(json.dumps(self.report))
        for update in (dict(skips=['old']),dict(tests_run=0,cases=[]),dict(errors=['old'])):
            self.report={**original,**update}
            with self.subTest(update=update),self.assertRaises(ValueError):self.ci.validate(head,self.base,stage='proposal')
        self.report=original;self.foreign=True
        with self.assertRaisesRegex(ValueError,'exact fixed isolated job'):self.ci.validate(head,self.base,stage='proposal')

    def test_branch_movement_after_job_never_grants_green_on_stale_proposal(self):
        head=self.propose();execute=self.execute
        def advancing(*args):
            result=execute(*args);self.repo.push(self.project.branch,head);return result
        self.runner.run.side_effect=advancing
        with self.assertRaises(EffectBlocked):self.ci.validate(head,self.base,stage='proposal')

    def test_new_discovery_hook_cannot_silently_omit_an_old_case(self):
        head=self.propose();self.report['cases']=['new_case_only']
        with self.assertRaisesRegex(ValueError,'omitted pre-existing test cases'):self.ci.validate(head,self.base,stage='proposal')

    def test_integrated_stage_requires_actual_branch_head_not_another_green_sha(self):
        head=self.propose()
        with self.assertRaises(EffectBlocked):self.ci.validate(head,self.base,stage='integrated')
        self.runner.run.assert_not_called();self.repo.push(self.project.branch,head)
        receipt=self.store.receipt(self.ci.validate(head,self.base,stage='integrated'))
        self.assertEqual(receipt['payload']['head'],head);self.assertEqual(receipt['payload']['stage'],'integrated')


if __name__=='__main__':unittest.main()
