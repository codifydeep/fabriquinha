"""Reassessment carries the exact current ruling and preserves TDD phase."""
import tempfile
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.repairs import context_view


class ReviewContext(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'private')
        self.scope=dict(actor='cto',number=75,kind='diagnostic')
        prior=self.store.record('diagnostic_experiment',dict(actor='cto',number=73),dict(report={'failures':['old']}))
        hold=self.store.record('diagnostic_decision',{},dict(experiment=prior,verdict={'reason':'Historical unverified conflict'}))
        current=self.store.record('diagnostic_experiment',self.scope,dict(project='project',incident='incident',report={'failures':['remaining']}))
        handoff=self.store.record('red',dict(kind='tests'),dict(snapshot='original'))
        self.value=dict(repair_kind='review',reviewed_diagnosis=hold,new_evidence=current,snapshot='original',handoff=handoff)
        self.data=dict(project='project',incident='incident',experiment=current,action='hold',
            verdict={'reason':'The conflict is feasible in the disposable copy.'},delivery_approval=False)

    def test_exact_current_ruling_is_delivered_without_inheriting_approval(self):
        receipt=self.store.record('diagnostic_decision',self.scope,self.data)
        result=context_view(self.store,self.value)
        self.assertEqual(result['current_diagnosis']['receipt'],receipt)
        self.assertEqual(result['current_diagnosis']['verdict'],self.data['verdict'])
        self.assertFalse(result['current_diagnosis']['grants_approval'])
        self.assertIn('Historical',result['prior_diagnosis']['reason'])
        self.assertEqual(result['review_phase'],'tests')
        self.assertIn('Green is not a prerequisite',result['start_condition'])
        self.assertIn('Expected Red',result['phase_contract'])

    def test_other_execution_incident_project_or_observation_is_not_a_ruling(self):
        for changes in ({'incident':'foreign'},{'project':'foreign'},{'experiment':'foreign'},{'delivery_approval':True}):
            self.store.record('diagnostic_decision',self.scope,{**self.data,**changes})
        self.store.record('diagnostic_decision',{**self.scope,'number':76},self.data)
        self.assertIsNone(context_view(self.store,self.value)['current_diagnosis'])

    def test_conflicting_rulings_fail_closed(self):
        self.store.record('diagnostic_decision',self.scope,self.data)
        self.store.record('diagnostic_decision',self.scope,{**self.data,'verdict':{'reason':'conflicting'}})
        with self.assertRaisesRegex(ValueError,'ambiguous ruling'):
            context_view(self.store,self.value)


if __name__=='__main__':unittest.main()
