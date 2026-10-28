"""Direct review permission is explicit, immutable and never delivery approval."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.repairs import record_review_admission,review_admission


class DirectReviewAdmission(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'private')
        self.project=SimpleNamespace(fingerprint=lambda:'project')
        self.binding=dict(actor='controller',task='anchor',release='release',contract='contract')
        self.graph=dict(project='project',items=[])
        self.cto=dict(actor='cto',task='spike',number=9,release='release')
        self.observation=self.store.record('diagnostic_experiment',self.cto,dict(project='project'))
        self.diagnosis=self.store.record('diagnostic_decision',self.cto,dict(project='project',incident='incident',
            experiment=self.observation,action='hold',delivery_approval=False))
        self.facts=dict(incident='incident',reviewed_diagnosis='held',handoff='red',new_evidence=self.observation,
            source='source',snapshot='original',delivery_approval=False)
        gate=patch('fabriquinha.repairs.review_reassessment',return_value=self.facts)
        self.gate=gate.start();self.addCleanup(gate.stop)

    def record(self):
        return record_review_admission(self.project,self.store,self.binding,self.graph,
            'incident','held','red',self.observation,self.diagnosis)

    def test_idempotent_explicit_controller_identity(self):
        key=self.record();self.assertEqual(self.record(),key)
        r=review_admission(self.project,self.store,key)
        self.assertEqual(r['binding']['actor'],'controller')
        self.assertEqual(r['kind'],'review_admission')
        self.assertFalse(r['payload']['delivery_approval'])
        self.assertNotIn('plan',r['payload'])

    def test_gate_is_revalidated_on_read(self):
        key=self.record();self.gate.side_effect=ValueError('changed snapshot')
        with self.assertRaisesRegex(ValueError,'changed snapshot'):review_admission(self.project,self.store,key)

    def test_approval_flags_foreign_graph_and_wrong_ruling_are_rejected(self):
        key=self.record();r=self.store.receipt(key)
        other_graph=self.store.record('release_graph',{**self.binding,'release':'foreign'},self.graph)
        wrong=self.store.record('diagnostic_decision',{**self.cto,'number':10},self.store.receipt(self.diagnosis)['payload'])
        for changes in ({'delivery_approval':True},{'protocol':'unknown'},{'snapshot':'other'},
                        {'prior_graph':other_graph},{'current_diagnosis':wrong}):
            bad=self.store.record('review_admission',self.binding,{**r['payload'],**changes})
            with self.subTest(changes=changes),self.assertRaises(ValueError):review_admission(self.project,self.store,bad)
        bad=self.store.record('review_admission',{**self.binding,'actor':'techlead'},r['payload'])
        with self.assertRaises(ValueError):review_admission(self.project,self.store,bad)


if __name__=='__main__':unittest.main()
