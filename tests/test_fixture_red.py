"""A fixture correction must produce fresh Red, never inherit a past pass."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from fixtures.control_evidence import frozen_evidence
from test_delivery_core import configuration
from test_fixture_revision import OLD,NEW


class FixtureRed(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);self.store=Store(root/'private');self.work=root/'work'
        (self.work/'tests').mkdir(parents=True)
        (self.work/'tests/test_existing.py').write_text('assert True\n')
        (self.work/'app.py').write_text('original product\n')
        self.baseline=self.store.capture(self.work)
        self.path='tests/acceptance_capacity.py';(self.work/self.path).write_text(OLD)
        self.frozen_snapshot=self.store.capture(self.work)
        self.project=Project.parse(configuration())
        old=Run('old-tests',1,'backend','tests',False,'backend','execution','old')
        self.freeze=frozen_evidence(self.store,self.project,old,self.baseline,self.frozen_snapshot,'lead')
        self.review=self.store.record('plan_review',replace(old,number=4,actor='cto',reviewing=True).binding(),{})
        self.authority=dict(review=self.review,context=dict(repair_kind='fixture',tests=self.freeze,snapshot=self.frozen_snapshot),
            proposal=dict(classification='test_contract',test_paths=[self.path]))
        (self.work/self.path).write_text(NEW);self.candidate=self.store.capture(self.work)
        self.run=Run('revised-tests',5,'backend','tests',False,'backend','execution','new')
        self.jobs=[];self.baseline_failure=False;self.all_green=False;self.inventory=['existing','new']
        self.board=SimpleNamespace(ensure=lambda run:None,input=lambda *args,**kwargs:self.red)
        self.quality=Quality(self.project,self.store,SimpleNamespace(run=self.execute),self.board)
        self.enterContext(patch('fabriquinha.repairs.repair_authority',return_value=self.authority))
        self.enterContext(patch('fabriquinha.repairs.reviewed',return_value=self.authority))

    def execute(self,run,snapshot,phase):
        self.jobs.append((snapshot,phase))
        cases=['existing'] if phase=='baseline' else self.inventory
        failed=(self.baseline_failure if phase=='baseline' else not self.all_green)
        failures=[dict(case=('existing' if phase=='baseline' else 'new'),assertion=True,
            frames=[dict(file=self.path,function='test_capacity')])] if failed else []
        return self.store.record('suite_job',run.binding(),dict(exit_code=int(failed),
            report=dict(version=1,tests_run=len(cases),cases=cases,failures=failures,errors=[],skips=[],expected_failures=[],unexpected_successes=[]),
            identity=dict(binding=run.binding(),project=self.project.fingerprint(),snapshot=snapshot,phase=phase,image=self.project.validation_image),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))

    def submit(self):
        self.red=self.quality.red(self.run,self.frozen_snapshot,self.candidate)
        return self.store.receipt(self.red)

    def test_fresh_original_baseline_and_red_then_exact_independent_freeze(self):
        record=self.submit()
        self.assertEqual(record['kind'],'red')
        self.assertEqual(self.jobs,[(self.baseline,'baseline'),(self.candidate,'red')])
        self.assertEqual(record['payload']['fixture_revision'],dict(authority=self.review,tests=self.freeze))
        review=replace(self.run,number=6,actor='lead',reviewing=True)
        frozen=self.quality.tests_review(review,self.red,dict(decision='approve',reason='Fixture setup reviewed independently.',findings=[]))
        data=self.quality.frozen_plan(self.store.receipt(frozen))
        self.assertEqual(data['snapshot'],self.candidate)
        self.assertEqual(data['control_cases'],['new'])
        forged=self.store.receipt(frozen);forged['binding']['actor']='unassigned'
        with self.assertRaises(ValueError):self.quality.frozen_plan(forged)
        self.assertEqual((self.store.tree(self.frozen_snapshot)/self.path).read_text(),OLD)

    def test_preserves_additional_independent_control_targets(self):
        old=self.store.receipt(self.freeze)['payload']
        board=SimpleNamespace(ensure=lambda run:None,input=lambda *a,**k:old['red'])
        reviewer=Run('old-tests',2,'lead','tests',True,'backend','execution','old')
        revised=Quality(self.project,self.store,None,board).tests_review(reviewer,old['red'],
            dict(decision='approve',reason='Additional regression risk.',findings=[]),
            control_risks=[dict(case='existing',reason='Prior behavior must remain covered.')])
        self.authority['context']['tests']=revised
        record=self.submit()
        self.assertEqual(self.quality.control_plan(record,[]),['existing','new'])

    def test_still_requires_red_and_green_baseline(self):
        self.all_green=True
        with self.assertRaises(ValueError):self.submit()
        self.all_green=False;self.baseline_failure=True
        with self.assertRaisesRegex(ValueError,'original baseline'):self.submit()

    def test_rejects_extra_or_missing_inventory(self):
        self.inventory=['existing','new','unapproved']
        with self.assertRaisesRegex(ValueError,'inventory'):self.submit()

    def test_product_changes_and_foreign_release_rejected_before_execution(self):
        (self.work/'app.py').write_text('changed product')
        self.candidate=self.store.capture(self.work)
        with self.assertRaises(ValueError):self.submit()
        self.assertEqual(self.jobs,[])
        (self.work/'app.py').write_text('original product\n');self.candidate=self.store.capture(self.work)
        self.run=replace(self.run,release='other')
        with self.assertRaises(ValueError):self.submit()
        self.assertEqual(self.jobs,[])

    def test_stale_authority_and_removed_history_cannot_freeze(self):
        record=self.submit()
        record['payload']['fixture_revision']['tests']='0'*64
        with self.assertRaises((ValueError,FileNotFoundError)):
            self.quality.control_plan(record,[])

if __name__=='__main__':unittest.main()
