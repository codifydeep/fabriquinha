from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store,digest
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
        self.project=Project.parse({**configuration(),'technical_roles':{'lead':'lead','cto':'cto'},'reviewers':{'backend':['lead','cto']}})
        self.run=Run('task',4,'backend','implementation',False,'backend','release',digest({'kind':'implementation'}))
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

    def test_runtime_error_in_a_sealed_mutant_routes_to_author_without_test_repair(self):
        from fabriquinha.recovery import Diagnostic, suite_refusal_context
        self.runner.control_submission=self.plan
        job=self.store.receipt(self.execute(self.run,self.mutants[0],'control'))
        payload=job['payload']
        payload['report'].update(errors=['new'],failures=[])
        key=self.store.record('suite_job',self.run.binding(),payload)
        later=replace(self.run,number=5)
        bind_claim(self.store,later,self.plan)
        result=suite_refusal_context(self.store,self.project,later.binding(),key,self.snapshot)
        self.assertEqual((result['owner'],result['control_issue'],result['green']),
                         ('backend','invalid_mutation',self.green))
        self.assertFalse(result['delivery_approval'])
        diag=Diagnostic.__new__(Diagnostic)
        diag.resolution={};diag.invalid_mutation=True;diag.level='cto'
        diag.incident={'resume_allowed':True}
        self.assertEqual(set(diag.actions()),{'hold','resume'})
        diag.incident['resume_allowed']=False
        self.assertEqual(diag.actions(),['hold'])

    def test_invalid_mutant_triage_requires_cto_experiment_and_one_scoped_return(self):
        from fabriquinha.control_return import invalid_control_retry
        self.runner.control_submission=self.plan
        payload=self.store.receipt(self.execute(self.run,self.mutants[0],'control'))['payload']
        payload['report'].update(errors=['new'],failures=[])
        job=self.store.record('suite_job',self.run.binding(),payload)
        body={'kind':'implementation'}
        live=replace(self.run,number=5)
        bind_claim(self.store,live,self.plan)
        project=self.project.fingerprint()
        incident=self.store.record('incident',live.binding(),dict(project=project,source_state='triage',controller_effects=[],
            resume_allowed=False,source=live.task,source_run=live.number,snapshot=self.snapshot,suite_refusal=job))
        actor=Run('decision',6,'cto','diagnostic',False,'cto',live.release,'decision-body')
        exp=self.store.record('diagnostic_experiment',actor.binding(),dict(project=project,snapshot=self.snapshot,incident=incident))
        choice=dict(action='return_controls',experiment=exp,incident=incident,delivery_approval=False,project=project)
        decision=self.store.record('diagnostic_decision',actor.binding(),choice)
        binding={'release':live.release,'actor':'controller'}
        cards=dict(implementation=dict(id=live.task,body=body,owner=live.author),tests=dict(id='tests'))
        graph=dict(project=project,items=[dict(cards=cards)])
        pointer=self.store.record('release_graph',binding,graph)
        wrong=self.store.record('release_graph',binding,{**graph,'items':[dict(cards={**cards,
            'implementation':{**cards['implementation'],'body':{'kind':'other'}}})]})
        with self.assertRaisesRegex(ValueError,'exact current author'):
            invalid_control_retry(self.project,self.store,decision,wrong)
        result=invalid_control_retry(self.project,self.store,decision,pointer)
        self.assertEqual(result['rejected_mutant'],self.mutants[0])
        exhausted=self.store.record('release_graph',binding,{**graph,'invalid_control_retries':[result['retry']]})
        with self.assertRaisesRegex(ValueError,'already returned'):
            invalid_control_retry(self.project,self.store,decision,exhausted)
        stale=self.store.record('diagnostic_decision',actor.binding(),{**choice,'experiment':None})
        with self.assertRaises(ValueError):invalid_control_retry(self.project,self.store,stale,pointer)

    def test_compact_repair_refuses_same_survivor_and_queues_the_complete_fresh_batch(self):
        from fabriquinha.quality import DeliveryTools
        from unittest.mock import Mock
        targets=[{'new':'assert the wrong result'},{'new':'assert the alternate wrong result'}]
        prior=seal(self.q,self.run,self.green,self.mutants,targets=targets)
        self.q.previous_controls=dict(submission=prior,green=self.green,freeze=self.freeze,controls=[
            dict(index=1,survived=False,observed=['new'],targets=targets[0],edits={'app.py':'value=2'}),
            dict(index=2,survived=True,observed=[],targets=targets[1],edits={'app.py':'value=3'})])
        sandbox=SimpleNamespace(board=self.board,store=self.store,project=self.project,run=self.run,
                                workspace=self.work,close=Mock())
        ops=DeliveryTools(sandbox,self.q)
        self.q.green=Mock(return_value=self.green);self.q.queue_controls=Mock(return_value={'scheduled':True})
        with self.assertRaisesRegex(ValueError,'surviving mutant'):
            ops.repair_controls({'replacements':{'2':{'app.py':'value=3'}}})
        self.q.green.assert_not_called()
        result=ops.repair_controls({'replacements':{'2':{'app.py':'value=4'}}})
        self.assertEqual(result,{'scheduled':True})
        self.q.green.assert_called_once_with(self.run,self.freeze,self.snapshot)
        new=self.store.receipt(self.q.queue_controls.call_args.args[1],kind='control_submission')['payload']
        self.assertEqual(new['targets'],targets)
        self.assertEqual(new['mutants'][0],self.mutants[0])
        self.assertNotEqual(new['mutants'][1],self.mutants[1])
        self.assertFalse(self.reviews)

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
