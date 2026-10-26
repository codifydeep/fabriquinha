"""Scripted controller facts only; these unit fixtures do not qualify delivery."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from fabriquinha.publication import Repository,LocalCI
from fabriquinha.effects import EffectBlocked
from test_delivery_core import configuration
from test_publication import git


class KnownRegression(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.work=Path(temp.name)/'work';(self.work/'tests').mkdir(parents=True)
        (self.work/'app.py').write_text('VALUE = 0\n')
        (self.work/'tests/test_existing.py').write_text('import unittest,app\nclass Existing(unittest.TestCase):\n def test_value(self): self.assertEqual(app.VALUE,1)\n def test_type(self): self.assertIsInstance(app.VALUE,int)\n')
        self.store=Store(Path(temp.name)/'private');self.project=Project.parse(configuration())
        self.base=self.store.capture(self.work);self.commit='a'*40
        self.author=Run('tests',1,'backend','tests',False,'backend','v2','test-contract')
        self.reviewer=replace(self.author,number=2,actor='lead',reviewing=True)
        self.implementer=Run('implementation',3,'backend','implementation',False,'backend','v2','impl-contract')
        self.inputs={'base_commit':self.commit};self.jobs=[];self.skips=[];self.errors=[]
        self.extra_failure=False;self.omit_case=False;self.drift=False
        self.board=SimpleNamespace(ensure=lambda run:None,input=lambda run,name,**kw:self.inputs[name])
        self.q=Quality(self.project,self.store,SimpleNamespace(run=self.execute),self.board)
        self.verdict=dict(decision='approve',reason='The existing assertion states the expected contract; only product repair is allowed.',findings=[])

    def report(self,phase):
        cases=['test_existing.Existing.test_value','test_existing.Existing.test_type']
        failures=[]
        if phase in ('baseline','red','control'):
            failures=[dict(case=cases[0],assertion=True,frames=[dict(file='tests/test_existing.py',function='test_value',line=3)])]
        if self.extra_failure:failures.append(dict(case=cases[1],assertion=True,frames=[dict(file='tests/test_existing.py',function='test_type',line=4)]))
        if self.omit_case:cases=cases[:1]
        if self.drift and phase=='red':failures[0]['frames'][0]['line']=4
        return dict(version=1,tests_run=len(cases),cases=cases,failures=failures,errors=self.errors,skips=self.skips,expected_failures=[],unexpected_successes=[])

    def execute(self,run,snapshot,phase):
        report=self.report(phase);self.jobs.append((snapshot,phase))
        return self.store.record('suite_job',run.binding(),dict(exit_code=int(bool(report['failures'] or report['errors'])),report=report,
            identity=dict(binding=run.binding(),project=self.project.fingerprint(),snapshot=snapshot,phase=phase,image=self.project.validation_image),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))

    def freeze(self):
        self.red=self.q.red(self.author,self.base,self.base);self.inputs['red']=self.red
        self.frozen=self.q.tests_review(self.reviewer,self.red,self.verdict);self.inputs['tests']=self.frozen
        return self.store.receipt(self.frozen)['payload']

    def test_existing_red_is_typed_frozen_and_fixed_without_duplicate_tests(self):
        frozen=self.freeze();red=self.q.test_evidence(self.red)
        self.assertEqual(red['kind'],'regression_red');self.assertEqual(red['payload']['base_commit'],self.commit)
        self.assertEqual(frozen['new_cases'],[]);self.assertEqual(frozen['control_cases'],['test_existing.Existing.test_value'])
        (self.work/'app.py').write_text('VALUE = 1\n');fixed=self.store.capture(self.work)
        green=self.q.green(self.implementer,self.frozen,fixed)
        (self.work/'app.py').write_text('VALUE = -1\n');mutant=self.store.capture(self.work)
        controls=self.q.controls(self.implementer,green,[mutant])
        self.assertEqual(self.store.receipt(controls)['payload']['coverage'],frozen['control_cases'])

    def test_a_failing_base_does_not_authorize_new_or_modified_tests(self):
        (self.work/'tests/test_new.py').write_text('import unittest\n')
        with self.assertRaises(ValueError):self.q.red(self.author,self.base,self.store.capture(self.work))
        self.assertFalse(any(phase=='red' for _,phase in self.jobs))

    def test_regression_needs_exact_controller_base_sha_not_an_agent_claim(self):
        self.inputs['base_commit']='not-a-sha'
        with self.assertRaises(ValueError):self.q.red(self.author,self.base,self.base)

    def test_regression_cannot_hide_skips_errors_or_unstable_failure_identity(self):
        for attribute,value in [('skips',['test_existing.Existing.test_type']),('errors',['test_existing.Existing.test_type']),('drift',True)]:
            with self.subTest(attribute=attribute):
                setattr(self,attribute,value)
                with self.assertRaises(ValueError):self.q.red(self.author,self.base,self.base)
                setattr(self,attribute,[] if attribute!='drift' else False)

    def test_test_freeze_is_independent_and_obsolete_input_is_rejected(self):
        self.red=self.q.red(self.author,self.base,self.base);self.inputs['red']=self.red
        with self.assertRaises(ValueError):self.q.tests_review(replace(self.reviewer,actor='backend'),self.red,self.verdict)
        self.inputs['red']='another-revision'
        with self.assertRaisesRegex(ValueError,'obsolete'):self.q.tests_review(self.reviewer,self.red,self.verdict)

    def test_implementation_cannot_weaken_the_existing_test(self):
        self.freeze();(self.work/'app.py').write_text('VALUE = 1\n')
        (self.work/'tests/test_existing.py').write_text('import unittest\n')
        with self.assertRaisesRegex(ValueError,'protected baseline'):self.q.green(self.implementer,self.frozen,self.store.capture(self.work))


class RegressionCIBoundaries(unittest.TestCase):
    report=KnownRegression.report
    execute=KnownRegression.execute
    freeze=KnownRegression.freeze

    def setUp(self):
        KnownRegression.setUp(self)
        root=self.work.parent;remote=root/'remote.git';remote.mkdir()
        git(remote,'init','--bare','--initial-branch=main');git(self.work,'init','--initial-branch=main');git(self.work,'add','.')
        git(self.work,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-m','Known defective fixture base')
        git(self.work,'remote','add','origin',str(remote));git(self.work,'push','origin','HEAD:refs/heads/'+self.project.branch)
        self.repo=Repository(self.project,self.store,remote=remote);self.commit=self.repo.base();self.inputs['base_commit']=self.commit
        self.ci=LocalCI(self.project,self.store,self.repo,self.q.runner)

    def candidate(self,*,review=True):
        self.freeze();(self.work/'app.py').write_text('VALUE = 1\n');snapshot=self.store.capture(self.work)
        green=self.q.green(self.implementer,self.frozen,snapshot);self.inputs['green']=green
        controls=self.q.controls(self.implementer,green,[self.base]);self.inputs['controls']=controls
        self.delivery=None
        if review:
            self.delivery=self.q.delivery_review(replace(self.implementer,number=4,actor='lead',reviewing=True),green,controls,self.verdict)
        head=self.repo.propose(snapshot,self.commit,'fixture/repair','fixture');self.repo.push('fixture/repair',head)
        return head

    def test_reviewed_regression_passes_proposal_and_integrated_ci_on_exact_sha(self):
        head=self.candidate();proposal=self.store.receipt(self.ci.validate(head,self.commit,stage='proposal'))['payload']
        self.assertEqual(proposal['conclusion'],'success');self.assertEqual(proposal['regression_review'],self.delivery)
        self.repo.push(self.project.branch,head)
        integrated=self.store.receipt(self.ci.validate(head,self.commit,stage='integrated'))['payload']
        self.assertEqual(integrated['conclusion'],'success');self.assertEqual(integrated['regression_review'],self.delivery)

    def test_test_review_alone_does_not_authorize_failing_ci_base(self):
        head=self.candidate(review=False)
        with self.assertRaises(EffectBlocked):self.ci.validate(head,self.commit,stage='proposal')

    def test_additional_base_failure_or_partial_inventory_is_rejected(self):
        head=self.candidate()
        for attribute in ('extra_failure','omit_case'):
            setattr(self,attribute,True)
            with self.subTest(attribute=attribute),self.assertRaises(ValueError):self.ci.validate(head,self.commit,stage='proposal')
            setattr(self,attribute,False)

    def test_a_green_review_does_not_approve_a_different_head_snapshot(self):
        self.candidate();(self.work/'app.py').write_text('VALUE = 2\n')
        head=self.repo.propose(self.store.capture(self.work),self.commit,'fixture/other','fixture');self.repo.push('fixture/other',head)
        with self.assertRaises(EffectBlocked):self.ci.validate(head,self.commit,stage='proposal')

    def test_identical_tree_at_different_base_sha_does_not_reuse_regression_approval(self):
        self.candidate();other=self.repo.propose(self.base,self.commit,'fixture/same-tree','fixture')
        self.repo.push(self.project.branch,other)
        head=self.repo.propose(self.store.capture(self.work),other,'fixture/rebased','fixture');self.repo.push('fixture/rebased',head)
        with self.assertRaises(EffectBlocked):self.ci.validate(head,other,stage='proposal')

    def test_known_base_failure_never_excuses_a_red_head(self):
        head=self.candidate();execute=self.execute
        # Preserve job provenance while introducing a genuine failed head report.
        def run(context,snapshot,phase):
            key=execute(context,snapshot,phase)
            if phase!='integrated':return key
            job=self.store.receipt(key);data=job['payload'];data['report']=self.report('control');data['exit_code']=1
            return self.store.record('suite_job',job['binding'],data)
        self.q.runner.run=run
        result=self.store.receipt(self.ci.validate(head,self.commit,stage='proposal'))['payload']
        self.assertEqual(result['conclusion'],'failure')


if __name__=='__main__':unittest.main()
