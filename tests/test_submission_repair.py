"""Pre-merge continuation facts never release native triage or waive quality."""
from dataclasses import replace
import unittest
from unittest.mock import patch
import test_control_targets as fixture_tools
from test_delivery_core import configuration
from fabriquinha.board import Run
from fabriquinha.repairs import submission_failure


class SubmissionRepairAdmission(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_tools.BehaviorControlTargets(methodName='runTest')
        with patch('test_control_targets.configuration',return_value={**configuration(),
                'technical_roles':dict(lead='lead',cto='cto')}):self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.freeze=f.freeze([dict(case='passing_risk',reason='Independent behavior risk')])
        green,mutant=f.green_and_mutant()
        with self.assertRaises(ValueError):f.q.controls(f.implementer,green,[mutant])
        self.snapshot=f.store.receipt(green)['payload']['snapshot']
        self.incident=dict(project=f.project.fingerprint(),source=f.implementer.task,
            source_run=f.implementer.number,source_state='triage',resume_allowed=False,
            controller_effects=[],snapshot=self.snapshot,control_refusal=f.q.control_refusal)
        self.diagnostic=Run('diagnosis',5,'cto','diagnostic',False,'cto','v1','diag-contract')

    def evaluate(self,*,incident=None,actor=None,experiment_snapshot=None,freeze=None,current=None):
        f=self.fixture;binding=(actor or self.diagnostic).binding()
        key=f.store.record('incident',f.implementer.binding(),incident or self.incident)
        experiment=f.store.record('diagnostic_experiment',binding,dict(project=f.project.fingerprint(),
            incident=key,snapshot=experiment_snapshot or self.snapshot))
        decision=f.store.record('diagnostic_decision',binding,dict(project=f.project.fingerprint(),
            incident=key,experiment=experiment,action='hold',delivery_approval=False))
        return submission_failure(f.project,f.store,key,decision,freeze or self.freeze,current or self.snapshot)

    def test_exact_facts_only_authorize_a_future_independent_proposal(self):
        value=self.evaluate()
        self.assertFalse(value['delivery_approval'])
        self.assertTrue(value['requires_independent_plan_review'])
        self.assertTrue(value['requires_fresh_green_and_controls'])
        self.assertEqual(value['tests'],self.freeze)
        self.assertEqual(value['control_refusal']['missing'],['passing_risk'])

    def test_live_or_changed_or_uncertain_source_is_not_a_continuation(self):
        for change in ({'source_state':'blocked'},{'resume_allowed':True},
                       {'source_run':99},{'source':'other'},{'controller_effects':['uncertain']}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.evaluate(incident={**self.incident,**change})
        with self.assertRaises(ValueError):self.evaluate(current=self.fixture.candidate)

    def test_other_role_release_or_experiment_is_rejected(self):
        for actor in (replace(self.diagnostic,actor='lead'),replace(self.diagnostic,release='other'),
                      replace(self.diagnostic,reviewing=True)):
            with self.subTest(actor=actor),self.assertRaises(ValueError):self.evaluate(actor=actor)
        with self.assertRaises(ValueError):self.evaluate(experiment_snapshot=self.fixture.candidate)

    def test_changed_frozen_tests_cannot_be_reused_as_continuation(self):
        f=self.fixture
        old=f.store.receipt(self.freeze,kind='tests_frozen')
        foreign=f.store.record('tests_frozen',{**old['binding'],'release':'other'},old['payload'])
        with self.assertRaises(ValueError):self.evaluate(freeze=foreign)


if __name__=='__main__':unittest.main()
