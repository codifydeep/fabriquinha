"""Scoped correction preserves the failed delivery and every unaffected test."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from contextlib import nullcontext
from dataclasses import replace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from fabriquinha.board import Run
from fabriquinha.artifacts import digest
from fabriquinha.repairs import reviewed,repair_document,Repairs,REPAIR_PROTOCOL
from fabriquinha.releases import Releases
from fabriquinha.effects import EffectBlocked
from fixtures.control_evidence import frozen_evidence
from test_delivery_core import configuration
from test_releases import configured


class RepairBoundaries(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'private');self.work=Path(temporary.name)/'work'
        (self.work/'tests').mkdir(parents=True)
        self.project=Project.parse(configured());self.board=Mock()
        self.quality=Quality(self.project,self.store,Mock(),self.board)
        self.path='tests/qa.json'
        self.check=dict(id='ROOM',path='/',actions=[dict(action='click',selector='#show')],selector='#result',text='Ana')
        (self.work/self.path).write_text(json.dumps(dict(version=1,checks=[self.check])))
        (self.work/'tests/test_existing.py').write_text('assert True\n')
        (self.work/'app.py').write_text('product\n');self.before=self.store.capture(self.work)

    def change(self,**fields):
        (self.work/self.path).write_text(json.dumps(dict(version=1,checks=[{**self.check,**fields}])))
        return self.store.capture(self.work)

    def test_only_explicit_qa_expectations_can_be_corrected(self):
        after=self.change(text='Hello, Ana!')
        self.quality.correction_diff(self.before,after,[self.path])
        with self.assertRaises(ValueError):self.quality.protect(self.before,after)
        for field in ({'selector':'#other'},{'actions':[]},{'id':'OTHER'}):
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.quality.correction_diff(self.before,self.change(**field),[self.path])

    def test_revision_never_authorizes_product_or_unittest_changes(self):
        self.change(text='Hello, Ana!')
        for path in ('app.py','tests/test_existing.py'):
            original=(self.work/path).read_text();(self.work/path).write_text('changed\n')
            with self.subTest(path=path),self.assertRaises(ValueError):
                self.quality.correction_diff(self.before,self.store.capture(self.work),[self.path])
            (self.work/path).write_text(original)
        with self.assertRaises(ValueError):
            self.quality.correction_diff(self.before,self.store.capture(self.work),['tests/test_existing.py'])

    def authority(self,prior):
        context=dict(project=self.project.fingerprint(),snapshot=self.before,tests=prior,qa_paths=[self.path])
        key=self.store.record('repair_context',dict(release='execution'),context)
        body=dict(version=1,kind='plan',release='execution',repair_of='integration',repair_context=key)
        author=Run('repair-plan',5,'lead','plan',False,'lead','execution',digest(body))
        proposal=self.store.record('work_plan',author.binding(),dict(project=self.project.fingerprint(),repair_body=body,
            document=dict(classification='test_contract',reason='The brief delegates wording; preserve every behavioral check.',test_paths=[self.path])))
        reviewer=replace(author,number=6,actor='cto',reviewing=True)
        receipt=self.store.record('plan_review',reviewer.binding(),dict(project=self.project.fingerprint(),plan=proposal,
            verdict=dict(decision='approve',reason='Independent technical correction; scope retained.',findings=[])))
        return receipt

    def test_correction_is_a_new_independent_revision_with_historical_red_not_a_fake_new_red(self):
        self.project=Project.parse({**configuration(),'coordination_roles':{'product':'product','lead':'lead'},
            'reviewers':{'qa':'lead','backend':'lead','lead':'cto'}})
        old=Run('old-tests',1,'qa','tests',False,'qa','execution','old-contract')
        prior=frozen_evidence(self.store,self.project,old,self.before,self.before,'lead')
        authority=self.authority(prior);inputs={'repair_review':authority}
        board=SimpleNamespace(ensure=lambda run:None,repair_input=lambda run:authority,review=Mock(),
            input=lambda run,name,**kw:inputs[name])
        def execute(run,snapshot,phase):
            failures=[dict(case='new',assertion=True,frames=[dict(file='tests/test_existing.py',function='test_behavior')])] if phase=='control' else []
            return self.store.record('suite_job',run.binding(),dict(exit_code=int(bool(failures)),
                identity=dict(binding=run.binding(),project=self.project.fingerprint(),snapshot=snapshot,phase=phase,image=self.project.validation_image),
                sandbox=dict(network='none',snapshot='readonly',user='65534:65534'),
                report=dict(version=1,tests_run=2,cases=['existing','new'],failures=failures,errors=[],skips=[],expected_failures=[],unexpected_successes=[])))
        quality=Quality(self.project,self.store,SimpleNamespace(run=execute),board)
        author=Run('new-tests',7,'qa','tests',False,'qa','execution','new-contract')
        after=self.change(text='Hello, Ana!')
        revision=quality.red(author,self.before,after);inputs['red']=revision
        receipt=self.store.receipt(revision)
        self.assertEqual(receipt['kind'],'test_revision')
        self.assertEqual(receipt['payload']['historical_tests'],prior)
        quality.handoff(author,'Independent review of the explicit test revision',{'red':revision})
        self.assertEqual(board.review.call_args.args[2],{'red':revision})
        inputs['tests']=quality.tests_review(replace(author,number=8,actor='lead',reviewing=True),revision,
            dict(decision='approve',reason='Expected text now follows approved wording; all checks remain.',findings=[]))
        with self.assertRaises(ValueError):quality.protect(self.before,after)
        quality.protect(self.before,after,allow_revision=True)
        implementation=Run('implementation',9,'backend','implementation',False,'backend','execution','implementation-contract')
        green=quality.green(implementation,inputs['tests'],after)
        (self.work/'app.py').write_text('broken\n');mutant=self.store.capture(self.work)
        controls=quality.controls(implementation,green,[mutant])
        self.assertEqual(self.store.receipt(controls)['payload']['coverage'],['new'])
        forged=self.store.record('test_revision',receipt['binding'],{**receipt['payload'],'control_cases':[]})
        with self.assertRaises(ValueError):quality.control_plan(self.store.receipt(forged),[])
        (self.work/'tests/test_existing.py').write_text('weakened\n')
        with self.assertRaises(ValueError):quality.protect(self.before,self.store.capture(self.work),allow_revision=True)

    def test_self_review_or_unapproved_test_path_never_grants_an_exception(self):
        receipt=self.authority('prior');record=self.store.receipt(receipt)
        bad=self.store.record('plan_review',{**record['binding'],'actor':'lead'},record['payload'])
        with self.assertRaises(ValueError):reviewed(self.project,self.store,bad)
        for document in (dict(classification='product',reason='Fix code',test_paths=[self.path]),
                         dict(classification='test_contract',reason='Change suite',test_paths=['tests/test_existing.py'])):
            with self.assertRaises(ValueError):repair_document(document,dict(qa_paths=[self.path]))

    def test_repeated_reconciliation_creates_one_native_proposal_without_resuming_the_failed_card(self):
        project=self.project;records={};created=[]
        anchor=SimpleNamespace(id='anchor',body=json.dumps(dict(release='execution')))
        source=SimpleNamespace(id='failed',status='triage')
        item=dict(package=dict(title='Greeting'),cards={'integration':{'id':source.id}})
        graph=dict(items=[item]);releases=Releases(project,self.store,self.board,Mock());repairs=Repairs(releases)
        context=self.store.record('repair_context',releases.binding(anchor),dict(project=project.fingerprint(),
            source=source.id,commit='a'*40,package=item['package']))
        def create(conn,**fields):
            created.append(fields);records['t_12345678']=SimpleNamespace(id='t_12345678',body=fields['body'],status='ready')
            return 't_12345678'
        conn=Mock();conn.execute.side_effect=lambda *a,**kw:SimpleNamespace(fetchall=lambda:[{'id':key,'body':task.body} for key,task in records.items()])
        kb=SimpleNamespace(create_task=create,get_task=lambda conn,key:records[key],unblock_task=Mock())
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch.object(Repairs,'context',return_value=context):
            item.update(repair_depth=2,repair_protocol='legacy',repair_attempts=2)
            self.assertEqual(repairs.reconcile(conn,anchor,dict(task='original-plan',approval='approved'),graph,Mock()),graph)
            self.assertEqual(Repairs(releases).reconcile(conn,anchor,dict(task='original-plan',approval='approved'),graph,Mock()),graph)
        self.assertEqual(len(created),1);self.assertEqual(created[0]['parents'],['original-plan'])
        self.assertEqual(json.loads(created[0]['body'])['repair_protocol'],REPAIR_PROTOCOL)
        self.assertEqual(source.status,'triage');kb.unblock_task.assert_not_called()
        records.clear();item.update(repair_protocol=REPAIR_PROTOCOL,repair_attempts=2)
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch.object(Repairs,'context',return_value=context):
            with self.assertRaisesRegex(EffectBlocked,'same protocol'):
                repairs.reconcile(conn,anchor,dict(task='original-plan',approval='approved'),graph,Mock())
        self.assertEqual(len(created),1)


if __name__=='__main__':unittest.main()
