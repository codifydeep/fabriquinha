"""New maintenance evidence and freeze lifecycle, using a synthetic suite runner."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import patch
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from test_releases import configured
from test_observer_maintenance import BEFORE, AFTER

CASE='acceptance_demo.Demo.test_ready'
class MaintenanceLifecycleTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);root=Path(t.name)
        self.store=Store(root/'private');self.work=root/'work';(self.work/'tests').mkdir(parents=True)
        (self.work/'app.py').write_text('value=1\n');(self.work/'tests/test_base.py').write_text('base')
        self.base=self.store.capture(self.work)
        self.path='tests/acceptance_demo.py';(self.work/self.path).write_text(BEFORE)
        self.delivered=self.store.capture(self.work)
        self.project=Project.parse({**configured(),'technical_roles':{'lead':'lead','cto':'cto'}})
        self.inputs={};self.board=SimpleNamespace(ensure=lambda r:None,input=lambda r,k,**kw:self.inputs[k])
        self.q=Quality(self.project,self.store,SimpleNamespace(run=self.execute),self.board)
        self.enterContext(patch.object(self.q,'browser_tests',return_value=None))
        self.old=Run('old',1,'qa','tests',False,'qa','old-release','old-contract')
        self.new_mode=False
        red=self.q.red(self.old,self.base,self.delivered);self.inputs['red']=red
        self.verdict=dict(decision='approve',reason='Independent synthetic review',findings=[])
        self.freeze=self.q.tests_review(replace(self.old,actor='lead',reviewing=True,number=2),red,self.verdict)
        (self.work/self.path).write_text(AFTER);self.candidate=self.store.capture(self.work)
        self.review=self.store.record('plan_review',dict(release='new-release'),{})
        self.facts=dict(paths=[self.path],tests=self.freeze,snapshot=self.delivered)
        self.enterContext(patch('fabriquinha.maintenance.reviewed',return_value=self.facts))
        self.board.maintenance_input=lambda r:self.review
        self.run=Run('new',3,'qa','tests',False,'qa','new-release','new-contract');self.new_mode=True

    def execute(self,run,snapshot,phase):
        cases=['test_base.Base.test_base']+([CASE] if self.path in self.store.manifest(snapshot) else [])
        failures=([dict(case=CASE,assertion=True,frames=[dict(file=self.path,function='test_ready',line=8)])]
                  if phase=='red' and not self.new_mode else [])
        return self.store.record('suite_job',run.binding(),dict(exit_code=int(bool(failures)),
            report=dict(version=1,tests_run=len(cases),cases=cases,failures=failures,errors=[],skips=[],expected_failures=[],unexpected_successes=[]),
            identity=dict(binding=run.binding(),project=self.project.fingerprint(),snapshot=snapshot,phase=phase,image=self.project.validation_image),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))

    def revision(self):
        key=self.q.red(self.run,self.delivered,self.candidate);self.inputs['red']=key;return key

    def test_new_revision_needs_independent_exact_freeze_before_ci(self):
        key=self.revision();record=self.store.receipt(key)
        self.assertEqual(record['kind'],'test_revision');self.assertEqual(record['payload']['new_cases'],[])
        self.assertNotEqual(record['payload']['baseline_job'],record['payload']['validation_job'])
        with self.assertRaises(ValueError):self.q.protect(self.delivered,self.candidate,allow_revision=True)
        frozen=self.q.tests_review(replace(self.run,actor='lead',reviewing=True,number=4),key,self.verdict)
        self.assertEqual(self.q.frozen_plan(self.store.receipt(frozen))['snapshot'],self.candidate)
        self.q.protect(self.delivered,self.candidate,allow_revision=True)

    def test_author_and_stale_handoff_rejected(self):
        key=self.revision()
        with self.assertRaises(ValueError):self.q.tests_review(replace(self.run,reviewing=True,number=4),key,self.verdict)
        self.inputs['red']='obsolete'
        with self.assertRaises(ValueError):self.q.tests_review(replace(self.run,actor='lead',reviewing=True,number=4),key,self.verdict)

    def test_foreign_suite_binding_rejected(self):
        key=self.revision();record=self.store.receipt(key)
        job=self.store.receipt(record['payload']['validation_job'])
        alien=self.store.record('suite_job',{**job['binding'],'task':'other'},job['payload'])
        forged=self.store.record('test_revision',self.run.binding(),{**record['payload'],'validation_job':alien})
        self.inputs['red']=forged
        with self.assertRaises(ValueError):self.q.tests_review(replace(self.run,actor='lead',reviewing=True,number=4),forged,self.verdict)

    def test_implementation_cannot_change_product_in_maintenance(self):
        key=self.revision()
        freeze=self.q.tests_review(replace(self.run,actor='lead',reviewing=True,number=4),key,self.verdict)
        self.inputs['tests']=freeze
        worker=Run('impl',5,'backend','implementation',False,'backend','new-release','impl-contract')
        self.q.green(worker,freeze,self.candidate)
        (self.work/'app.py').write_text('value=2\n')
        with self.assertRaisesRegex(ValueError,'cannot change delivered product'):
            self.q.green(worker,freeze,self.store.capture(self.work))
