"""A done card is not enough to release a reviewed plan or a deployment."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import json
import sqlite3

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store, digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked
from fabriquinha.releases import Releases, ordered
from test_delivery_core import configuration
from test_intake import document, work


def configured():
    return {**configuration(),'coordination_roles':{'product':'product','lead':'lead'},
            'delivery_roles':{'tests':'qa','integration':'devops'},
            'reviewers':{'backend':['lead','cto'],'qa':'lead','lead':'cto','devops':'qa'},
            'browser_image':'sha256:'+'b'*64}


class ReleaseContracts(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'private');self.project=Project.parse(configured())
        self.board=Mock();self.intake=Mock()
        self.releases=Releases(self.project,self.store,self.board,self.intake)

    def test_historical_package_cannot_reach_release_acceptance_under_the_new_contract(self):
        old=dict(binding={},payload=dict(project=self.project.fingerprint(),control_contract=1))
        item=dict(cards={'tests':dict(id='tests'),'implementation':dict(id='implementation'),'integration':dict(id='integration')})
        self.releases.closed=Mock(return_value=('old-freeze',old,{}))
        with self.assertRaisesRegex(ValueError,'historical control contract'):
            self.releases.package_evidence(item,{})
        self.releases.closed.assert_called_once_with('tests','tests','tests_frozen')

    def test_delivery_roles_are_explicit_reviewed_and_immutable(self):
        value=configured();parsed=Project.parse(value);value['delivery_roles']['tests']='changed'
        self.assertEqual(parsed.delivery_roles['tests'],'qa')
        self.assertNotEqual(parsed.fingerprint(),Project.parse(configuration()).fingerprint())
        for roles in ({'tests':'qa','integration':'qa'},{'tests':'unknown','integration':'devops'},{'tests':'qa'}):
            with self.subTest(roles=roles),self.assertRaises(ValueError):
                Project.parse({**configured(),'delivery_roles':roles})

    def test_plan_order_preserves_dependencies_not_caller_array_order(self):
        tasks=list(reversed(work()['tasks']))
        self.assertEqual([item['id'] for item in ordered(tasks)],['room','join'])
        tasks[1]['depends_on']=['join']
        with self.assertRaises(ValueError):ordered(tasks)

    def test_managed_body_is_derived_from_reviewed_package_not_worker_arguments(self):
        body=self.releases.body('tests','execution','anchor','plan-review',work()['tasks'][0],{'baseline':'snapshot'})
        self.assertEqual(body['release_plan'],'plan-review')
        self.assertEqual(body['criteria'],['ROOM'])
        self.assertEqual(body['inputs'],{'baseline':'snapshot'})
        self.assertNotIn('approved',body)
        self.assertNotIn('command',body)

    def test_native_bound_pr_is_allowed_only_with_its_own_publication_provenance(self):
        body=dict(kind='integration',release='execution');url=self.project.repository+'/pull/3'
        task=SimpleNamespace(id='integration',body=json.dumps(body),completion_contract=url)
        publication=self.store.record('publication',dict(task=task.id,contract=digest(body),release='execution'),dict(pr=url))
        integrated=self.store.record('integrated',{},dict(publication=publication))
        artifact=self.store.record('artifact',{},dict(integrated=integrated))
        rollout=self.store.record('rollout',{},dict(candidate=artifact))
        conn=Mock();conn.execute.return_value.fetchone.return_value={'metadata':json.dumps(dict(rollout=rollout,published_pr=url))}
        self.assertTrue(self.releases.bound_contract(conn,task))
        task.completion_contract=self.project.repository+'/pull/4'
        self.assertFalse(self.releases.bound_contract(conn,task))

    def test_closed_receipt_requires_exact_native_run_and_project(self):
        run=Run('task',8,'lead','implementation',True,'backend','execution','contract')
        self.board.closed_review.return_value=(run,{'delivery':'key'},{'green':'green'})
        good=self.store.record('delivery_review',run.binding(),{'project':self.project.fingerprint()})
        self.board.closed_review.return_value=(run,{'delivery':good},{'green':'green'})
        self.assertEqual(self.releases.closed('task','delivery','delivery_review')[0],good)
        old=self.store.record('delivery_review',{**run.binding(),'number':7},{'project':self.project.fingerprint()})
        self.board.closed_review.return_value=(run,{'delivery':old},{'green':'green'})
        with self.assertRaises(ValueError):self.releases.closed('task','delivery','delivery_review')
        foreign=self.store.record('delivery_review',run.binding(),{'project':'other'})
        self.board.closed_review.return_value=(run,{'delivery':foreign},{'green':'green'})
        with self.assertRaises(ValueError):self.releases.closed('task','delivery','delivery_review')

    def test_dependent_baseline_requires_parent_qa_before_author_work_begins(self):
        run=Run('tests',10,'qa','tests',False,'qa','execution','contract')
        self.board.input.return_value='snapshot'
        body={'inputs':{'baseline':'parent:previous:baseline'}}
        self.board.closed_review.side_effect=ValueError('manual done lacks independent QA')
        with self.assertRaises(ValueError):self.releases.baseline(run,body)
        self.board.closed_review.side_effect=None
        parent=Run('previous',8,'qa','integration',True,'devops','execution','parent-contract')
        artifact=self.store.record('artifact',{},dict(project=self.project.fingerprint(),snapshot='snapshot'))
        qa=self.store.record('release_evidence',parent.binding(),dict(project=self.project.fingerprint(),artifact=artifact))
        self.board.closed_review.return_value=(parent,{'release_evidence':qa},{})
        self.assertEqual(self.releases.baseline(run,body),'snapshot')
        self.board.input.return_value='different'
        with self.assertRaises(ValueError):self.releases.baseline(run,body)

    def test_release_identity_is_not_a_current_worker_claim(self):
        anchor=SimpleNamespace(id='release',body='{"release":"execution"}')
        binding=self.releases.binding(anchor)
        self.assertEqual(binding,dict(actor='controller',task='release',release='execution',contract=digest({'release':'execution'})))
        self.assertNotIn('number',binding)

    def test_missing_roles_do_not_change_old_isolated_runtime(self):
        old=Releases(Project.parse(configuration()),self.store,self.board,self.intake)
        self.assertEqual(old.reconcile(Mock(),Mock()),{})
        self.intake.roots.assert_not_called()

    def test_interrupted_graph_creation_cannot_dispatch_partial_work(self):
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('CREATE TABLE task_links(parent_id,child_id)')
        tasks={};keys={};created=[0];unblocked=[]
        anchor=SimpleNamespace(id='anchor',body=json.dumps(dict(release='c'*64)))
        source=self.store.root.parent/'seed';source.mkdir();(source/'app.py').write_text('baseline')
        seed=self.store.record('release_seed',self.releases.binding(anchor),dict(snapshot=self.store.capture(source),commit='a'*40))
        def create(_,**value):
            if value['idempotency_key'] in keys:return keys[value['idempotency_key']]
            created[0]+=1
            if created[0]==2:raise RuntimeError('interrupted before graph publication')
            task_id='task-'+str(len(tasks));keys[value['idempotency_key']]=task_id
            tasks[task_id]=SimpleNamespace(id=task_id,status=value['initial_status'],assignee=value['assignee'],body=value['body'],
                workspace_path=value['workspace_path'],workspace_kind=value['workspace_kind'],completion_contract=value['completion_contract'])
            conn.executemany('INSERT INTO task_links VALUES(?,?)',[(parent,task_id) for parent in value['parents']])
            return task_id
        def unblock(_,task):
            self.assertTrue((self.releases.folder(anchor)/'graph.json').is_file())
            unblocked.append(task);tasks[task].status='ready';return True
        kb=SimpleNamespace(create_task=create,get_task=lambda _,task:tasks[task],latest_run=lambda *args:None,unblock_task=unblock)
        spec=dict(task='plan-task',review='review',document=work())
        with patch('fabriquinha.releases.native',return_value=(kb,None,None)),patch.object(self.releases,'seed',return_value=seed):
            with self.assertRaises(RuntimeError):self.releases.materialize(conn,anchor,spec,Mock())
            self.assertEqual(len(tasks),1);self.assertEqual(unblocked,[])
            self.assertEqual(next(iter(tasks.values())).status,'blocked')
            _,graph=self.releases.materialize(conn,anchor,spec,Mock())
            self.assertEqual(len(tasks),6);self.assertEqual(len(unblocked),6)
            second=graph['items'][1]['cards']['tests']
            first=graph['items'][0]['cards']['integration']['id']
            self.assertIn(first,second['parents'])
            self.assertEqual(second['body']['inputs']['baseline'],'parent:'+first+':baseline')
            unblocked.clear();self.releases.materialize(conn,anchor,spec,Mock());self.assertEqual(unblocked,[])

    def test_final_qa_must_cover_the_whole_brief_not_only_the_last_package(self):
        seed=self.store.record('release_seed',{},dict(snapshot='baseline',commit='base'))
        graph=dict(seed=seed,items=[dict(cards={'integration':dict(id='integrator')})])
        evidence=dict(checks=['ROOM'],commit='a'*40,qa='qa')
        kb=SimpleNamespace(get_task=lambda *args:SimpleNamespace(status='done'),complete_task=Mock())
        services=Mock()
        with patch('fabriquinha.releases.native',return_value=(kb,None,None)),patch.object(self.releases,'package_evidence',return_value=evidence):
            with self.assertRaisesRegex(ValueError,'every approved criterion'):
                self.releases.accept(Mock(),Mock(),dict(brief=document()),'graph',graph,services)
        services.assert_not_called();kb.complete_task.assert_not_called()

    def test_a_past_qa_receipt_cannot_homologate_a_changed_or_unhealthy_service(self):
        seed=self.store.record('release_seed',{},dict(snapshot='baseline',commit='base'))
        qa=self.store.record('release_evidence',{},dict(artifact='artifact',container='container',image='image',url='http://127.0.0.1:1'))
        graph=dict(seed=seed,items=[dict(cards={'integration':dict(id='integrator')})])
        evidence=dict(checks=['ROOM','JOIN'],commit='a'*40,qa=qa)
        kb=SimpleNamespace(get_task=lambda *args:SimpleNamespace(status='done'),complete_task=Mock());services=Mock()
        with patch('fabriquinha.releases.native',return_value=(kb,None,None)), \
             patch.object(self.releases,'package_evidence',return_value=evidence),patch('fabriquinha.releases.Deployment') as deployment:
            deployment.return_value.service.return_value=dict(healthy=False)
            with self.assertRaises(EffectBlocked):self.releases.accept(Mock(),Mock(),dict(brief=document()),'graph',graph,services)
        kb.complete_task.assert_not_called();services.assert_not_called()


if __name__=='__main__':unittest.main()
