"""Admission is provenance, never permission to bypass triage or quality."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.repairs import held_incident,review_failure

class SuccessionAdmission(unittest.TestCase):
    def setUp(self):
        self.project=SimpleNamespace(technical_roles={'cto':'cto'},fingerprint=lambda:'project')
        source=dict(kind='tests',reviewing=True,task='source',number=7,release='release')
        reviewer=dict(kind='diagnostic',reviewing=False,actor='cto',release='release')
        self.records={
            'incident':dict(kind='incident',binding=source,payload=dict(project='project',source_state='triage',source='source',source_run=7,resume_allowed=False,controller_effects=[],snapshot='snapshot')),
            'decision':dict(kind='diagnostic_decision',binding=reviewer,payload=dict(project='project',incident='incident',action='hold',delivery_approval=False,experiment='experiment')),
            'experiment':dict(kind='diagnostic_experiment',binding=copy.deepcopy(reviewer),payload=dict(project='project',incident='incident',snapshot='snapshot'))}
        def receipt(key,kind):
            value=self.records[key]
            if value['kind']!=kind:raise ValueError('wrong receipt kind')
            return value
        self.store=SimpleNamespace(receipt=receipt)

    def admit(self):return held_incident(self.project,self.store,'incident','decision','snapshot')

    def test_review_hold_is_read_only_admission_not_resume(self):
        before=copy.deepcopy(self.records)
        incident,decision=self.admit()
        self.assertFalse(incident['payload']['resume_allowed'])
        self.assertFalse(decision['payload']['delivery_approval'])
        self.assertEqual(self.records,before)

    def test_rejects_stale_source_foreign_experiment_and_pending_effect(self):
        for key,field,value in [('incident','source_run',8),('incident','snapshot','changed'),
                ('incident','controller_effects',['pending']),('decision','incident','other'),
                ('experiment','snapshot','other'),('experiment','project','other')]:
            with self.subTest(key=key,field=field):
                original=self.records[key]['payload'][field]
                self.records[key]['payload'][field]=value
                with self.assertRaises(ValueError):self.admit()
                self.records[key]['payload'][field]=original

    def test_non_cto_or_foreign_release_cannot_authorize_succession(self):
        for field,value in [('actor','author'),('release','other'),('reviewing',True)]:
            with self.subTest(field=field):
                original=self.records['decision']['binding'][field]
                self.records['decision']['binding'][field]=value
                with self.assertRaises(ValueError):self.admit()
                self.records['decision']['binding'][field]=original

    def test_implementation_review_uses_exact_author_snapshot(self):
        source=self.records['incident']['binding']
        source.update(kind='implementation',actor='lead',author='developer',contract='contract')
        author={**source,'number':6,'actor':'developer','reviewing':False}
        self.records['green']=dict(kind='green',binding=author,payload=dict(project='project',snapshot='snapshot'))
        facts=review_failure(self.project,self.store,'incident','decision','green')
        self.assertEqual(facts['snapshot'],'snapshot')
        self.assertFalse(facts['delivery_approval'])
        for field,value in [('actor','lead'),('task','other'),('contract','other'),('release','other')]:
            with self.subTest(field=field):
                original=author[field];author[field]=value
                with self.assertRaises(ValueError):review_failure(self.project,self.store,'incident','decision','green')
                author[field]=original
        self.records['green']['payload']['snapshot']='different'
        with self.assertRaises(ValueError):review_failure(self.project,self.store,'incident','decision','green')

    def test_authorship_is_not_a_delivery_review(self):
        self.records['incident']['binding']['reviewing']=False
        with self.assertRaisesRegex(ValueError,'held delivery review'):
            review_failure(self.project,self.store,'incident','decision','absent')
