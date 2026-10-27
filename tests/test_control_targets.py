"""Behavior controls do not require corrupting immutable QA metadata."""
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
from test_delivery_core import configuration


class BehaviorControlTargets(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.work=self.root/'work';(self.work/'tests').mkdir(parents=True)
        (self.work/'app.py').write_text('VALUE = 0\n')
        (self.work/'tests/test_existing.py').write_text('existing test\n')
        self.store=Store(self.root/'private');self.baseline=self.store.capture(self.work)
        (self.work/'tests/test_feature.py').write_text('feature and QA metadata assertions\n')
        self.candidate=self.store.capture(self.work);self.project=Project.parse(configuration())
        self.author=Run('tests',1,'backend','tests',False,'backend','v1','tests-contract')
        self.reviewer=replace(self.author,number=2,actor='lead',reviewing=True)
        self.implementer=Run('implementation',3,'backend','implementation',False,'backend','v1','implementation-contract')
        self.inputs={};self.calls=[]
        self.board=SimpleNamespace(ensure=lambda r:None,input=lambda run,name,**kw:self.inputs[name])
        self.failing=['feature']
        def execute(run,snapshot,phase):
            cases=['existing'] if phase=='baseline' else ['existing','feature','qa_metadata','passing_risk']
            if phase=='control' and getattr(self,'omit_auxiliary',False):cases.remove('qa_metadata')
            failing=['feature'] if phase=='red' else self.failing if phase=='control' else []
            report=dict(version=1,tests_run=len(cases),cases=cases,errors=[],skips=getattr(self,'skips',[]),expected_failures=[],unexpected_successes=[],
                failures=[dict(case=case,assertion=True,frames=[dict(file='tests/test_feature.py',function='test_behavior')]) for case in failing])
            self.calls.append((snapshot,phase))
            return self.store.record('suite_job',run.binding(),dict(exit_code=int(bool(failing)),report=report,
                identity=dict(binding=run.binding(),snapshot=snapshot,phase=phase,project=self.project.fingerprint(),image=self.project.validation_image),
                sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
        self.q=Quality(self.project,self.store,SimpleNamespace(run=execute),self.board)
        self.red=self.q.red(self.author,self.baseline,self.candidate);self.inputs['red']=self.red
        self.approval=dict(decision='approve',reason='Feature Red covers acceptance; QA metadata is an invariant.',findings=[])

    def freeze(self,risks=()):
        result=self.q.tests_review(self.reviewer,self.red,self.approval,control_risks=list(risks))
        self.inputs['tests']=result
        return result

    def green_and_mutant(self):
        (self.work/'app.py').write_text('VALUE = 1\n');green=self.q.green(self.implementer,self.inputs['tests'],self.store.capture(self.work))
        (self.work/'app.py').write_text('VALUE = -1\n')
        return green,self.store.capture(self.work)

    def test_product_behavior_can_be_qualified_while_qa_metadata_stays_passing(self):
        freeze=self.freeze();data=self.store.receipt(freeze,kind='tests_frozen')['payload']
        self.assertEqual(data['control_cases'],['feature'])
        self.assertIn('qa_metadata',data['cases'])
        green,mutant=self.green_and_mutant()
        controls=self.q.controls(self.implementer,green,[mutant])
        self.assertEqual(self.store.receipt(controls)['payload']['coverage'],['feature'])
        self.assertEqual(self.calls[-1],(mutant,'control'))

    def test_reviewer_can_require_a_passing_risk_and_author_cannot_ignore_it(self):
        self.freeze([dict(case='passing_risk',reason='A passing security assertion still needs a negative control.')])
        green,mutant=self.green_and_mutant()
        with self.assertRaises(ValueError) as error:self.q.controls(self.implementer,green,[mutant])
        self.assertIn('"missing": ["passing_risk"]',str(error.exception))
        self.assertIn('"covered": ["feature"]',str(error.exception))
        self.assertIn('preserve the full suite and frozen tests',str(error.exception))
        refusal=self.store.receipt(self.q.control_refusal,kind='control_refusal')
        self.assertEqual(refusal['binding'],self.implementer.binding())
        self.assertEqual(refusal['payload']['green'],green)
        self.assertEqual(refusal['payload']['feedback']['missing'],['passing_risk'])
        self.assertEqual(refusal['payload']['missing'],['passing_risk'])
        self.assertEqual(refusal['payload']['coverage'],['feature'])
        self.assertFalse(refusal['payload']['delivery_approval'])
        self.assertFalse(any(self.store.receipt(p.stem)['kind']=='controls' for p in (self.store.root/'receipts').glob('*.json')))
        self.failing=['feature','passing_risk']
        self.q.controls(self.implementer,green,[mutant])
        self.assertIsNone(self.q.control_refusal)

    def test_unjustified_unknown_duplicate_or_nonapproval_risks_are_rejected(self):
        for risks in ([dict(case='unknown',reason='risk')],[dict(case='qa_metadata',reason='')],
                      [dict(case='qa_metadata',reason='risk')]*2,[dict(case='feature',reason='Already mandatory')]):
            with self.subTest(risks=risks),self.assertRaises(ValueError):self.freeze(risks)
        changes=dict(decision='changes',reason='Fix coverage',findings=[dict(path='app.py',line=1,detail='Missing behavior assertion')])
        with self.assertRaises(ValueError):self.q.tests_review(self.reviewer,self.red,changes,control_risks=[dict(case='qa_metadata',reason='risk')])

    def test_partial_submissions_do_not_accumulate_but_combined_mutants_cover_targets(self):
        self.freeze([dict(case='passing_risk',reason='Independent passing behavior needs a negative control.')])
        green,first=self.green_and_mutant()
        (self.work/'app.py').write_text('VALUE = -2\n');second=self.store.capture(self.work)
        execute=self.q.runner.run
        def targeted(run,snapshot,phase):
            self.failing=['feature'] if snapshot==first else ['passing_risk']
            return execute(run,snapshot,phase)
        self.q.runner.run=targeted
        for mutant in (first,second):
            with self.assertRaisesRegex(ValueError,'Separate failed submissions do not accumulate coverage'):
                self.q.controls(self.implementer,green,[mutant])
        controls=self.q.controls(self.implementer,green,[first,second])
        self.assertEqual(self.store.receipt(controls)['payload']['coverage'],['feature','passing_risk'])
        self.assertIsNone(self.q.control_refusal)

    def test_altered_target_set_and_legacy_freeze_cannot_become_current_evidence(self):
        freeze=self.freeze();receipt=self.store.receipt(freeze)
        for updates in ({'control_cases':[]},{'control_cases':['qa_metadata']},{'control_contract':1}):
            bad=self.store.record('tests_frozen',receipt['binding'],{**receipt['payload'],**updates})
            self.inputs['tests']=bad
            with self.subTest(updates=updates),self.assertRaises(ValueError):self.q.freeze(self.implementer,bad)

    def test_auxiliary_test_remains_protected_after_freeze(self):
        self.freeze();(self.work/'tests/test_feature.py').write_text('weakened\n')
        with self.assertRaises(ValueError):self.q.green(self.implementer,self.inputs['tests'],self.store.capture(self.work))

    def test_no_effect_partial_inventory_and_skip_controls_remain_rejected(self):
        self.freeze();green,mutant=self.green_and_mutant()
        self.failing=[]
        with self.assertRaises(ValueError):self.q.controls(self.implementer,green,[mutant])
        self.failing=['feature'];self.omit_auxiliary=True
        with self.assertRaises(ValueError):self.q.controls(self.implementer,green,[mutant])
        self.omit_auxiliary=False;self.skips=['qa_metadata']
        with self.assertRaises(ValueError):self.q.controls(self.implementer,green,[mutant])

    def test_historical_red_is_not_converted_by_a_new_review(self):
        receipt=self.store.receipt(self.red);payload={k:v for k,v in receipt['payload'].items() if k!='control_contract'}
        old=self.store.record('red',receipt['binding'],payload);self.inputs['red']=old
        with self.assertRaises(ValueError):self.q.tests_review(self.reviewer,old,self.approval)
        self.assertFalse(any(self.store.receipt(p.stem)['kind']=='tests_frozen' for p in (self.store.root/'receipts').glob('*.json')))


if __name__=='__main__':unittest.main()
