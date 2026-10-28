"""Model-facing operations derive phase and evidence from the controller."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality, DeliveryTools
from test_delivery_core import configuration
from fixtures.control_evidence import red_evidence


class ModelDeliveryOperations(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.store=Store(self.root/'private')
        self.project=Project.parse(configuration())
        self.workspace=self.root/'work';(self.workspace/'tests').mkdir(parents=True)
        (self.workspace/'app.py').write_text('VALUE = 1\n')
        (self.workspace/'tests/test_existing.py').write_text('baseline test\n')
        self.baseline=self.store.capture(self.workspace)
        self.run=Run('tests',1,'backend','tests',False,'backend','v1','contract')
        self.events=[]
        self.board=SimpleNamespace(ensure=lambda run:None,input=lambda *a,**k:self.baseline,
            review=lambda *a,**k:self.events.append(('handoff',k)),
            finish_review=lambda *a,**k:self.events.append(('finish',a,k)))
        self.quality=Quality(self.project,self.store,None,self.board)
        self.sandbox=SimpleNamespace(project=self.project,store=self.store,board=self.board,run=self.run,
            workspace=self.workspace,close=lambda:self.events.append(('close',)))
        self.tools=DeliveryTools(self.sandbox,self.quality)

    def test_test_submission_uses_controller_baseline_and_closes_before_handoff(self):
        def red(run,baseline,snapshot):
            self.assertEqual((run,baseline),(self.run,self.baseline))
            return self.store.record('red',run.binding(),dict(project=self.project.fingerprint(),snapshot=snapshot))
        self.quality.red=Mock(side_effect=red)
        result=self.tools.submit({})
        self.assertEqual([event[0] for event in self.events],['close','handoff'])
        self.assertEqual(result['status'],'review_requested')
        self.assertFalse(result['delivery_approval'])

    def test_pass_flags_or_caller_identity_cannot_replace_test_evidence(self):
        self.quality.red=Mock()
        for args in ({'passed':True},{'run':self.run.binding()},{'baseline':self.baseline}):
            with self.subTest(args=args),self.assertRaises(ValueError):self.tools.submit(args)
        self.quality.red.assert_not_called();self.assertEqual(self.events,[])

    def test_failed_gate_preserves_author_activity_for_correction(self):
        self.quality.red=Mock(side_effect=ValueError('not a real Red'))
        with self.assertRaises(ValueError):self.tools.submit({})
        self.assertEqual(self.events,[])
        (self.workspace/'tests/test_new.py').write_text('corrected test\n')
        seen=[]
        def red(run,baseline,snapshot):
            seen.append(snapshot)
            return self.store.record('red',run.binding(),dict(project=self.project.fingerprint(),snapshot=snapshot))
        self.quality.red=red;self.tools.submit({})
        self.assertNotEqual(seen[0],self.baseline)

    def test_mutants_are_derived_from_green_and_cannot_change_frozen_tests(self):
        run=replace(self.run,kind='implementation')
        self.sandbox.run=run
        tools=DeliveryTools(self.sandbox,self.quality)
        for mutant in ({'tests/test_existing.py':'weakened'}, {'../escape':'bad'}, {'new.py':'bad'}):
            with self.subTest(mutant=mutant),self.assertRaises(ValueError):
                tools.mutants(self.baseline,[mutant])
        result=tools.mutants(self.baseline,[{'app.py':'VALUE = 0\n'}])
        self.assertEqual(len(result),1)
        self.assertEqual((self.store.tree(result[0])/'app.py').read_text(),'VALUE = 0\n')
        self.assertEqual((self.store.tree(result[0])/'tests/test_existing.py').read_text(),'baseline test\n')
        self.assertEqual((self.workspace/'app.py').read_text(),'VALUE = 1\n')

    def test_exact_mutation_edits_are_independent_and_preserve_source(self):
        edits=[{'app.py':{'before':'VALUE = 1','after':'VALUE = 0'}},
               {'app.py':{'before':'VALUE = 1','after':'VALUE = 2'}}]
        result=self.tools.mutants(self.baseline,edits)
        self.assertEqual([(self.store.tree(x)/'app.py').read_text() for x in result],
                         ['VALUE = 0\n','VALUE = 2\n'])
        self.assertEqual((self.workspace/'app.py').read_text(),'VALUE = 1\n')
        for edit in ({'before':'','after':'x'}, {'before':'missing','after':'x'},
                     {'before':'VALUE','after':'VALUE'}, {'before':'VALUE','after':'x','count':1},
                     {'before':1,'after':'x'}):
            with self.subTest(edit=edit),self.assertRaises(ValueError):
                self.tools.mutants(self.baseline,[{'app.py':edit}])
        with self.assertRaises(ValueError):
            self.tools.mutants(self.baseline,[{'tests/test_existing.py':{'before':'baseline','after':'weakened'}}])
        (self.workspace/'app.py').write_text('VALUE VALUE\n')
        repeated=self.store.capture(self.workspace)
        with self.assertRaises(ValueError):
            self.tools.mutants(repeated,[{'app.py':{'before':'VALUE','after':'x'}}])

    def test_author_cannot_use_review_operation(self):
        with self.assertRaises(ValueError):self.tools.review(dict(decision='approve',reason='invalid self review',findings=[]))
        self.assertEqual(self.events,[])

    def test_independent_test_review_freezes_exact_handoff_then_finishes_native_review(self):
        red=red_evidence(self.store,self.project,self.run,self.baseline,self.baseline)
        self.board.input=lambda *args,**kwargs:red
        self.sandbox.run=replace(self.run,number=2,actor='lead',reviewing=True)
        tools=DeliveryTools(self.sandbox,self.quality)
        result=tools.review(dict(decision='approve',reason='Valid independent fixture review',findings=[]))
        self.assertEqual([event[0] for event in self.events],['close','finish'])
        self.assertEqual(self.events[-1][2],{'changes':False})
        receipt=self.store.receipt(self.events[-1][1][2]['tests'],kind='tests_frozen')
        self.assertEqual(receipt['payload']['red'],red)
        self.assertEqual(result['status'],'completed')

    def test_review_impasse_records_changes_and_escalates_without_freeze_or_approval(self):
        red=self.store.record('red',self.run.binding(),dict(project=self.project.fingerprint(),snapshot=self.baseline,
            baseline=self.baseline,cases=['existing','new'],new_cases=['new']))
        self.board.input=lambda *args,**kwargs:red
        self.board.escalate_review=Mock()
        self.sandbox.run=replace(self.run,number=2,actor='lead',reviewing=True)
        tools=DeliveryTools(self.sandbox,self.quality)
        result=tools.review(dict(decision='escalate',reason='Need a CTO experiment',
            findings=[dict(path='app.py',line=1,detail='Clarify behavior using an isolated experiment')]))
        record=self.store.receipt(result['escalation'],kind='review_escalation')
        review=self.store.receipt(record['payload']['review'],kind='test_review')
        self.assertEqual(review['payload']['verdict']['decision'],'changes')
        self.assertEqual(record['binding'],self.sandbox.run.binding())
        self.assertEqual(record['payload']['snapshot'],self.baseline)
        self.assertEqual([event[0] for event in self.events],['close'])
        self.board.escalate_review.assert_called_once_with(self.sandbox.run,result['escalation'])
        self.assertFalse(result['delivery_approval'])

    def review_history(self,*,paths=('app.py','app.py'),foreign=False):
        result=[]
        for number,path in zip((2,4),paths):
            run=replace(self.run,number=number,actor='lead',reviewing=True)
            verdict=dict(decision='changes',reason='Unresolved independent review concern',findings=[dict(path=path,line=1,detail='Verify the expected behavior')])
            key=self.store.record('test_review',run.binding(),dict(project='f'*64 if foreign else self.project.fingerprint(),snapshot=self.baseline,verdict=verdict))
            result.append(dict(receipt=key,run=number,reviewer='lead',verdict=verdict,snapshot=self.baseline))
        self.board.review_feedback=lambda *args:result
        return result

    def test_repeated_review_changes_escalate_without_the_model_requesting_it(self):
        history=self.review_history()
        red=red_evidence(self.store,self.project,self.run,self.baseline,self.baseline)
        self.board.input=lambda *args,**kwargs:red
        self.sandbox.run=replace(self.run,number=6,actor='lead',reviewing=True)
        self.board.escalate_review=Mock();tools=DeliveryTools(self.sandbox,self.quality)
        result=tools.review(dict(decision='changes',reason='Still blocked in the same artifact',findings=[dict(path='app.py',line=1,detail='The review issue remains')]))
        self.assertEqual(result['status'],'technical_diagnosis_requested')
        record=self.store.receipt(result['escalation'],kind='review_escalation')
        self.assertEqual(record['payload']['recurrence']['reviews'],[h['receipt'] for h in history])
        self.assertEqual(record['payload']['recurrence']['paths'],['app.py'])
        self.board.escalate_review.assert_called_once_with(self.sandbox.run,result['escalation'])
        self.assertEqual([event[0] for event in self.events],['close'])

    def test_review_churn_is_not_a_handoff_counter_or_permission_to_skip_approval(self):
        history=self.review_history(paths=('app.py','tests/test_existing.py'))
        run=replace(self.run,number=6,actor='lead',reviewing=True)
        changes=dict(decision='changes',reason='A different concern',findings=[dict(path='app.py',line=1,detail='Another issue')])
        self.assertIsNone(self.quality.review_recurrence(run,changes))
        self.board.review_feedback=lambda *args:history[:1]
        self.assertIsNone(self.quality.review_recurrence(run,changes))
        self.review_history()
        self.assertIsNone(self.quality.review_recurrence(run,dict(decision='approve',reason='Corrected',findings=[])))
        self.quality.review_after=5
        self.assertIsNone(self.quality.review_recurrence(run,changes))
        self.quality.review_after=0
        self.review_history(foreign=True)
        with self.assertRaises(ValueError):self.quality.review_recurrence(run,changes)

    def test_only_the_test_reviewer_can_freeze_additional_control_risks(self):
        red=red_evidence(self.store,self.project,self.run,self.baseline,self.baseline)
        self.board.input=lambda *args,**kwargs:red
        self.sandbox.run=replace(self.run,number=2,actor='lead',reviewing=True)
        result=DeliveryTools(self.sandbox,self.quality).review(dict(decision='approve',reason='Baseline risk reviewed',findings=[],
            control_risks=[dict(case='existing',reason='The existing behavior is critical for this change.')]))
        frozen=self.store.receipt(result['evidence']['tests'],kind='tests_frozen')
        self.assertEqual(frozen['payload']['control_cases'],['existing','new'])
        self.sandbox.run=replace(self.sandbox.run,kind='implementation')
        with self.assertRaises(ValueError):DeliveryTools(self.sandbox,self.quality).review(dict(
            decision='approve',reason='Cannot choose targets during delivery review',findings=[],control_risks=[]))
