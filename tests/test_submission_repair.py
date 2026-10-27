"""Pre-merge continuation facts never release native triage or waive quality."""
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
import test_control_targets as fixture_tools
from test_delivery_core import configuration
from fabriquinha.board import Run
from fabriquinha.artifacts import digest
from fabriquinha.repairs import submission_failure,repair_document,Repairs,reviewed,SUBMISSION_PROTOCOL


class SubmissionRepairAdmission(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_tools.BehaviorControlTargets(methodName='runTest')
        with patch('test_control_targets.configuration',return_value={**configuration(),
                'technical_roles':dict(lead='lead',cto='cto'),
                'coordination_roles':dict(product='product',lead='lead')}):self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.source_body=dict(version=1,kind='implementation',release='v1',release_anchor='anchor')
        f.implementer=replace(f.implementer,contract=digest(self.source_body))
        self.freeze=f.freeze([dict(case='passing_risk',reason='Independent behavior risk')])
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

    def test_submission_proposal_cannot_authorize_test_or_business_changes(self):
        context=dict(repair_kind='submission',qa_paths=[])
        proposal=dict(classification='submission',reason='Submit all independently targeted mutations together.',test_paths=[])
        self.assertEqual(repair_document(proposal,context),proposal)
        for classification in ('product','test_contract'):
            with self.assertRaises(ValueError):repair_document({**proposal,'classification':classification},context)
        with self.assertRaises(ValueError):repair_document({**proposal,'test_paths':['tests/test_existing.py']},context)
        with self.assertRaises(ValueError):repair_document(proposal,dict(qa_paths=[]))
        for classification in ('infrastructure','scope'):
            self.assertEqual(repair_document({**proposal,'classification':classification},context)['classification'],classification)

    def test_native_proposal_is_idempotent_and_does_not_release_source(self):
        f=self.fixture;facts=self.evaluate();(f.work/'app.py').write_text('VALUE = 1\n')
        source=SimpleNamespace(id=f.implementer.task,status='triage',body=json.dumps(self.source_body),workspace_path=f.work)
        tests=SimpleNamespace(id='tests',status='done');anchor=SimpleNamespace(id='anchor')
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE tasks(id TEXT,body TEXT,idempotency_key TEXT)');created=[]
        def create(connection,**kwargs):
            created.append(kwargs);connection.execute('INSERT INTO tasks VALUES(?,?,?)',('proposal',kwargs['body'],kwargs['idempotency_key']))
            return 'proposal'
        kb=SimpleNamespace(latest_run=lambda *a:SimpleNamespace(id=f.implementer.number,ended_at=1),create_task=create)
        releases=SimpleNamespace(project=f.project,store=f.store,board=SimpleNamespace(guard=None),
            check_card=lambda c,card:source if card['id']==source.id else tests,
            closed=lambda *a:(self.freeze,None,None),binding=lambda a:dict(actor='controller',task=a.id,release='v1',contract='anchor'))
        spec=dict(task='approved-plan',approval='approved-brief',document=dict(architecture='HTTP',observability='local'))
        item=dict(cards=dict(implementation={'id':source.id},tests={'id':tests.id}),package=dict(id='first',title='First'))
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]):
            operation=Repairs(releases)
            first=operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'])
            self.assertEqual(operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis']),first)
            self.assertEqual(len(created),1);self.assertEqual(source.status,'triage')
            self.assertEqual(created[0]['assignee'],'lead');self.assertEqual(created[0]['parents'],['approved-plan'])
            self.assertEqual(json.loads(created[0]['body'])['repair_of'],source.id)
            conn.execute('UPDATE tasks SET body=?',(json.dumps({'altered':True}),))
            with self.assertRaises(ValueError):operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'])

    def test_continuation_requires_independent_review_of_exact_source_facts(self):
        f=self.fixture;facts=self.evaluate()
        def approval(actor='cto',source_run=None):
            context={**facts,'project':f.project.fingerprint(),'repair_kind':'submission',
                'submission_protocol':SUBMISSION_PROTOCOL,'qa_paths':[]}
            if source_run is not None:context['source_run']=source_run
            key=f.store.record('repair_context',dict(release='v1'),context)
            body=dict(repair_context=key,repair_protocol=SUBMISSION_PROTOCOL,repair_of=f.implementer.task)
            author=Run('proposal',6,'lead','plan',False,'lead','v1',digest(body))
            proposal=f.store.record('work_plan',author.binding(),dict(project=f.project.fingerprint(),repair_body=body,
                document=dict(classification='submission',reason='Retain all useful controls in a single submission.',test_paths=[])))
            reviewer=replace(author,number=7,actor=actor,reviewing=True)
            return f.store.record('plan_review',reviewer.binding(),dict(project=f.project.fingerprint(),plan=proposal,
                verdict=dict(decision='approve',reason='The scoped proposal preserves quality gates.',findings=[])))
        self.assertEqual(reviewed(f.project,f.store,approval())['proposal']['classification'],'submission')
        with self.assertRaises(ValueError):reviewed(f.project,f.store,approval(actor='lead'))
        with self.assertRaises(ValueError):reviewed(f.project,f.store,approval(source_run=999))


if __name__=='__main__':unittest.main()
