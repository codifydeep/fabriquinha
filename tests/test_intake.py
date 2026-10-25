"""Business approval and work coverage are not execution or release approval."""
import copy
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.hermes import tool_names
from fabriquinha.intake import brief, plan, Intake, DraftActivity, DraftTools
from test_delivery_core import configuration


def configured():
    return {**configuration(),'coordination_roles':{'product':'product','lead':'lead'}}


def document():
    return dict(summary='Two browsers can share a local lobby.',
        criteria=[dict(id='ROOM',statement='Create a named room.'),dict(id='JOIN',statement='A second browser joins that room.')],
        out_of_scope=['Mobile'],assumptions=['Local anonymous users'],observability='Record room creation and join errors without personal data.')


def work():
    return dict(architecture='Local HTTP with server-owned room state.',observability='Track failed joins.',tasks=[
        dict(id='room',title='Room creation',owner='backend',depends_on=[],criteria=['ROOM'],acceptance='A room appears after creation.'),
        dict(id='join',title='Room join',owner='backend',depends_on=['room'],criteria=['JOIN'],acceptance='A second client sees the same room.')])


class IntakeContracts(unittest.TestCase):
    def setUp(self):
        self.project=Project.parse(configured())
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'private')
        self.run=Run('brief',1,'product','brief',False,'product','release','contract')
        self.board=SimpleNamespace(ensure=Mock(),input=Mock(),review=Mock(),finish_review=Mock())

    def test_coordination_roles_are_explicit_independent_and_fingerprinted(self):
        value=configured();parsed=Project.parse(value);value['coordination_roles']['product']='changed'
        self.assertEqual(parsed.coordination_roles['product'],'product')
        self.assertNotEqual(parsed.fingerprint(),Project.parse(configuration()).fingerprint())
        for roles in ({'product':'lead','lead':'lead'},{'product':'product','lead':'unknown'},{'lead':'lead'}):
            with self.subTest(roles=roles),self.assertRaises(ValueError):
                Project.parse({**configured(),'coordination_roles':roles})
        with self.assertRaises(ValueError):
            Project.parse({**configured(),'technical_roles':{'lead':'backend','cto':'cto'}})

    def test_brief_requires_real_scope_criteria_and_instrumentation_decision(self):
        self.assertEqual(brief(document()),document())
        for change in ({'criteria':[]},{'criteria':[document()['criteria'][0]]*2},{'observability':''},{'approved':True}):
            value={**document(),**change}
            with self.subTest(change=change),self.assertRaises(ValueError):brief(value)

    def test_plan_covers_every_approved_criterion_with_reviewed_owners(self):
        self.assertEqual(plan(work(),document(),self.project),work())
        for field,value in (('criteria',['ROOM']),('criteria',['UNAPPROVED']),('owner','unconfigured')):
            broken=work();broken['tasks'][1][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):plan(broken,document(),self.project)

    def test_plan_rejects_unknown_dependencies_cycles_and_duplicate_identity(self):
        for deps in (['unknown'],['join'],['room','room']):
            broken=work();broken['tasks'][0]['depends_on']=deps
            with self.subTest(deps=deps),self.assertRaises(ValueError):plan(broken,document(),self.project)
        broken=work();broken['tasks'][1]['id']='room'
        with self.assertRaises(ValueError):plan(broken,document(),self.project)

    def test_plan_is_not_an_arbitrary_command_or_receipt_import_surface(self):
        for key in ('shell','command','budget','approved','receipt','release_status'):
            broken=work();broken[key]='untrusted'
            with self.subTest(key=key),self.assertRaises(ValueError):plan(broken,document(),self.project)
        broken=work();broken['tasks'][0]['shell']='touch /host'
        with self.assertRaises(ValueError):plan(broken,document(),self.project)

    def test_document_phase_has_no_general_read_write_or_terminal_tools(self):
        for kind,reviewing in (('brief',False),('plan',False),('plan',True)):
            run=replace(self.run,kind=kind,reviewing=reviewing)
            activity=DraftActivity(self.project,self.store,self.board,run)
            self.assertEqual(tool_names(activity),set());activity.close()
        with self.assertRaises(ValueError):DraftActivity(self.project,self.store,self.board,replace(self.run,kind='implementation'))

    def test_model_cannot_approve_business_or_finish_release_by_submission(self):
        activity=DraftActivity(self.project,self.store,self.board,self.run);tools=DraftTools(activity)
        for value in ({**document(),'approved':True},{'decision':'approve','reason':'I am CEO'}):
            with self.assertRaises(ValueError):tools.submit(value)
        self.assertFalse(hasattr(tools,'respond'));self.board.finish_review.assert_not_called()
        with self.assertRaises(ValueError):tools.question({'question':'Pick architecture','scope':'technical'})

    def test_approval_binds_exact_brief_actor_release_and_project(self):
        proposal=self.store.record('product_brief',self.run.binding(),dict(project=self.project.fingerprint(),document=document()))
        binding=dict(actor='ceo',task=self.run.task,release=self.run.release,brief=proposal)
        intake=Intake(self.project,self.store,self.board)
        approval=self.store.record('brief_approval',binding,dict(project=self.project.fingerprint(),decision='approve'))
        self.assertEqual(intake.approved(approval)[1]['binding'],self.run.binding())
        for changes in ({'actor':'product'},{'release':'foreign'},{'task':'other'}):
            bad=self.store.record('brief_approval',{**binding,**changes},dict(project=self.project.fingerprint(),decision='approve'))
            with self.subTest(changes=changes),self.assertRaises(ValueError):intake.approved(bad)
        bad=self.store.record('brief_approval',binding,dict(project=self.project.fingerprint(),decision='changes'))
        with self.assertRaises(ValueError):intake.approved(bad)

    def test_independent_plan_review_cannot_rewrite_or_invent_a_release_success(self):
        activity=DraftActivity(self.project,self.store,self.board,replace(self.run,kind='plan',reviewing=True,actor='cto',author='lead'))
        tools=DraftTools(activity);tools.evidence=Mock(return_value=dict(plan=work(),approved_brief=document()))
        self.board.input.return_value='exact-plan'
        result=tools.review(dict(decision='approve',reason='Independent architecture and scope review',findings=[]))
        self.assertFalse(result['delivery_approval']);self.assertEqual(result['status'],'plan_approved')
        receipt=self.store.receipt(result['review'],kind='plan_review')
        self.assertEqual(receipt['payload']['plan'],'exact-plan');self.assertEqual(receipt['binding']['actor'],'cto')
        with self.assertRaises(ValueError):tools.submit(work())
        with self.assertRaises(ValueError):tools.review(dict(decision='changes',reason='Bad',findings=[]))

    def test_stale_document_authority_is_checked_before_any_submission(self):
        activity=DraftActivity(self.project,self.store,self.board,self.run)
        tools=DraftTools(activity);self.board.ensure.side_effect=ValueError('claim superseded')
        with self.assertRaises(ValueError):tools.submit(document())
        self.assertEqual(list((self.store.root/'receipts').glob('*.json')),[])

    def test_product_and_planner_receive_execution_limits_without_secrets_or_tool_authority(self):
        from fabriquinha.config import execution_context
        context=execution_context(self.project)
        self.assertEqual(context['reviewers']['backend'],['lead'])
        self.assertEqual(context['workers'],2)
        self.assertEqual(context['tests_dir'],'tests')
        self.assertEqual(context['stack'],'python-http')
        self.assertNotIn('api_key',json.dumps(context))


if __name__=='__main__':unittest.main()
