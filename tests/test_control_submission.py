from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.control_submission import advance,seal,NextControl,bind_claim
from fabriquinha.recovery import control_refusal_context
from fabriquinha.effects import EffectBlocked
from fabriquinha.quality import Quality,product_mutations
from fixtures.control_evidence import frozen_evidence
from test_delivery_core import configuration


class ControlContinuation(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root=Path(temp.name); self.work=root/'work'; self.work.mkdir()
        (self.work/'app.py').write_text('value=1')
        self.store=Store(root/'private'); self.snapshot=self.store.capture(self.work)
        self.project=Project.parse({**configuration(),'reviewers':{'backend':['lead','cto']}})
        self.run=Run('task',4,'backend','implementation',False,'backend','release','contract')
        author=Run('tests',1,'lead','tests',False,'lead','release','tests-contract')
        self.freeze=frozen_evidence(self.store,self.project,author,self.snapshot,self.snapshot,'cto')
        self.green=self.store.record('green',self.run.binding(),dict(project=self.project.fingerprint(),freeze=self.freeze,snapshot=self.snapshot))
        self.reviews=[]; self.executions=[]
        self.board=SimpleNamespace(ensure=lambda r:None,input=lambda r,key:self.freeze,workspace=lambda r:self.work,
                                   review=lambda *a,**kw:self.reviews.append((a,kw)))
        self.runner=SimpleNamespace(run=self.execute)
        self.q=Quality(self.project,self.store,self.runner,self.board)
        self.mutants=product_mutations(self.q,self.snapshot,[{'app.py':'value=2'},{'app.py':'value=3'}])
        self.plan=seal(self.q,self.run,self.green,self.mutants)
        self.case='new'
        self.survives=set()

    def execute(self,run,tree,phase):
        self.executions.append(tree)
        failures=[] if tree in self.survives else [dict(case=self.case,assertion=True,frames=[dict(file='tests/test_new.py',function='test_behavior')])]
        return self.store.record('suite_job',run.binding(),dict(exit_code=int(bool(failures)),report=dict(version=1,tests_run=2,
            cases=['existing','new'],failures=failures,
            errors=[],skips=[],expected_failures=[],unexpected_successes=[]),identity=dict(binding=run.binding(),project=self.project.fingerprint(),
            snapshot=tree,phase=phase,image=self.project.validation_image,control_submission=self.runner.control_submission),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))

    def test_restart_new_claim_reuses_checks_and_hands_off_original_green(self):
        with self.assertRaises(NextControl):advance(self.q,replace(self.run,number=5),self.plan)
        self.assertFalse(self.reviews)
        result=advance(self.q,replace(self.run,number=6),self.plan)
        self.assertEqual(self.executions,self.mutants)
        self.assertEqual(result['evidence']['green'],self.green)
        controls=self.store.receipt(result['evidence']['controls'],kind='controls')
        self.assertEqual(controls['binding'],self.run.binding())
        self.assertEqual(self.reviews[0][1],{'exclude':('lead',)})

    def test_missing_target_blocks_even_after_restart(self):
        self.case='existing'
        with self.assertRaises(NextControl):advance(self.q,self.run,self.plan)
        with self.assertRaisesRegex(ValueError,'did not witness'):advance(self.q,replace(self.run,number=5),self.plan)
        self.assertFalse(self.reviews)
        live=replace(self.run,number=5)
        bind_claim(self.store,live,self.plan)
        feedback=control_refusal_context(self.store,self.project,live.binding(),self.q.control_refusal,self.snapshot)
        self.assertEqual(feedback['missing'],['new'])
        with self.assertRaises(ValueError):
            control_refusal_context(self.store,self.project,replace(live,number=6).binding(),self.q.control_refusal,self.snapshot)

    def test_changed_workspace_or_subject_or_freeze_refused(self):
        with self.assertRaises(ValueError):advance(self.q,replace(self.run,author='other'),self.plan)
        old=self.freeze;self.freeze='changed'
        with self.assertRaises(ValueError):advance(self.q,self.run,self.plan)
        self.freeze=old;(self.work/'app.py').write_text('different')
        with self.assertRaises(EffectBlocked):advance(self.q,self.run,self.plan)
        self.assertFalse(self.executions)

    def test_surviving_mutant_remains_veto_after_rest_of_batch_is_observed(self):
        self.survives.add(self.mutants[0])
        with self.assertRaises(NextControl):advance(self.q,self.run,self.plan)
        with self.assertRaisesRegex(ValueError,'surviving controls'):
            advance(self.q,replace(self.run,number=5),self.plan)
        receipt=self.store.receipt(self.q.control_refusal,kind='control_refusal')['payload']
        self.assertEqual(receipt['missing'],[])
        self.assertEqual(receipt['surviving'][0]['index'],1)
        self.assertEqual(len(receipt['jobs']),2)
        self.assertEqual(self.executions,self.mutants)
        self.assertFalse(self.reviews)
