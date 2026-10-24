"""Native integration waits release claims; no extra lifecycle database."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store, digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import Pending, EffectBlocked, write_json
from fabriquinha.runtime import Runtime, IntegrationRunner, recorded_worker
from test_delivery_core import configuration


class IntegrationLifecycle(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        write_json(self.root/'project.json',configuration())
        with patch('fabriquinha.runtime.bind'):
            self.runtime=Runtime(self.root,self.root/'upstream')
        self.body=dict(version=1,kind='integration',release='v1',inputs={'delivery':'approved'})
        self.run=Run('integration',7,'lead','integration',False,'lead','v1',digest(self.body))

    def api(self,conn,kb=None):
        return patch('fabriquinha.runtime.native',return_value=(kb or Mock(),
            SimpleNamespace(connect_closing=lambda:closing(conn)),None))

    def test_pending_integration_is_scheduled_with_exact_durable_authority(self):
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        conn.execute.return_value.fetchone.return_value=dict(worker_pid=os.getpid(),worker_started_at='fp',claim_lock='local')
        kb=Mock();self.runtime.board=Mock()
        with patch('fabriquinha.runtime.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:conn),None)):
            self.runtime.park_integration(self.run,now=100)
        kb.schedule_task.assert_called_once()
        args=kb.schedule_task.call_args.kwargs
        self.assertEqual(args['expected_run_id'],7)
        key=json.loads(args['reason'])['integration_wait']
        receipt=self.runtime.store.receipt(key,kind='integration_wait')
        self.assertEqual(receipt['binding'],self.run.binding())
        self.assertEqual(receipt['payload']['wake_at'],115)
        self.assertEqual(receipt['payload']['project'],self.runtime.project.fingerprint())

    def test_review_cannot_silently_be_scheduled_back_as_implementation(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            self.runtime.park_integration(replace(self.run,reviewing=True))

    def test_wait_reconciler_uses_native_unblock_and_refuses_live_old_worker_or_changed_contract(self):
        def scenario(*,alive=False,body=None,assignee='lead',now=116,cleared=False):
            conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
            conn.executescript('CREATE TABLE tasks(id,body,status,assignee,current_run_id);'
                'CREATE TABLE task_runs(id,task_id,profile,outcome,ended_at,worker_pid,worker_started_at,claim_lock);'
                'CREATE TABLE task_events(id,task_id,run_id,kind,payload);')
            key=self.runtime.store.record('integration_wait',self.run.binding(),
                dict(project=self.runtime.project.fingerprint(),wake_at=115))
            conn.execute('INSERT INTO tasks VALUES(?,?,?,?,NULL)',
                (self.run.task,json.dumps(body or self.body),'scheduled',assignee))
            conn.execute('INSERT INTO task_runs VALUES(?,?,?,?,?,?,?,?)',
                (7,self.run.task,'lead','scheduled',101,None if cleared else 123,None if cleared else 'fp','local'))
            conn.execute('INSERT INTO task_events VALUES(1,?,?,?,?)',
                (self.run.task,7,'scheduled',json.dumps({'reason':json.dumps({'integration_wait':key})})))
            conn.execute('INSERT INTO task_events VALUES(0,?,?,?,?)',
                (self.run.task,7,'spawned',json.dumps({'pid':123,'started_at':'fp'})))
            kb=Mock()
            with patch('fabriquinha.runtime.native',return_value=(kb,None,None)), \
                 patch('fabriquinha.runtime.worker_alive',return_value=alive) as liveness:
                issues=self.runtime.wake_integrations(conn,now=now)
                if cleared:
                    self.assertEqual(liveness.call_args.args[0]['worker_pid'],123)
            conn.close()
            return kb,issues
        kb,issues=scenario();kb.unblock_task.assert_called_once();self.assertEqual(issues,{})
        kb,issues=scenario(now=110);kb.unblock_task.assert_not_called()
        kb,issues=scenario(alive=True);kb.unblock_task.assert_not_called()
        kb,issues=scenario(cleared=True)
        kb.unblock_task.assert_called_once();self.assertEqual(issues,{})
        kb,issues=scenario(cleared=True,alive=True);kb.unblock_task.assert_not_called()
        kb,issues=scenario(body={**self.body,'release':'other'})
        kb.unblock_task.assert_not_called();self.assertIn(self.run.task,issues)
        kb,issues=scenario(assignee='backend')
        kb.unblock_task.assert_not_called();self.assertIn(self.run.task,issues)

    def test_integration_requires_native_pr_completion_contract_before_effects(self):
        self.runtime.board=Mock();repo=Mock();github=Mock();quality=Mock()
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        kb=Mock();kb.get_task.return_value=SimpleNamespace(completion_contract='local-only')
        with patch('fabriquinha.runtime.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:conn),None)), \
             patch.object(self.runtime,'integration_services',return_value=(repo,github)), \
             patch('fabriquinha.runtime.Publication') as publication:
            with self.assertRaisesRegex(ValueError,'PR completion contract'):
                self.runtime.integrate(self.run,quality)
        publication.assert_not_called()

    def test_cleared_pid_requires_matching_native_spawn_event_not_a_death_assumption(self):
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.executescript('CREATE TABLE task_events(id,task_id,run_id,kind,payload);')
        row=dict(id=7,task_id='integration',worker_pid=None,worker_started_at=None,claim_lock='local')
        with self.assertRaises(EffectBlocked):recorded_worker(conn,row)
        conn.execute('INSERT INTO task_events VALUES(1,?,?,?,?)',
            ('other-task',7,'spawned',json.dumps({'pid':123,'started_at':'fp'})))
        with self.assertRaises(EffectBlocked):recorded_worker(conn,row)
        conn.execute('INSERT INTO task_events VALUES(2,?,?,?,?)',
            ('integration',7,'worker_registered',json.dumps({'pid':123,'started_at':'fp'})))
        restored=recorded_worker(conn,row)
        self.assertEqual((restored['worker_pid'],restored['worker_started_at']),(123,'fp'))
        with self.assertRaises(EffectBlocked):recorded_worker(conn,{**row,'worker_pid':456})

    def test_integration_pipeline_uses_exact_review_and_hands_rollout_to_independent_qa(self):
        self.runtime.board=Mock();self.runtime.board.input.return_value='review'
        repo=Mock();github=Mock();quality=Mock()
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        kb=Mock();kb.get_task.return_value=SimpleNamespace(completion_contract='example/product')
        with patch('fabriquinha.runtime.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:conn),None)), \
             patch.object(self.runtime,'integration_services',return_value=(repo,github)), \
             patch('fabriquinha.runtime.Publication') as publication, \
             patch('fabriquinha.runtime.Deployment') as deployment:
            pub=publication.return_value;pub.publish.return_value='published'
            pub.validate_integrated.return_value='integrated'
            delivery=deployment.return_value;delivery.artifact.side_effect=['baseline','candidate']
            delivery.rollout.return_value='rollout'
            record=self.runtime.store.record('publication',self.run.binding(),{'pr':'https://github.com/example/product/pull/1'})
            pub.publish.return_value=record
            self.runtime.integrate(self.run,quality)
            pub.publish.assert_called_once_with(self.run,'review')
            pub.validate_integrated.assert_called_once_with(self.run,record,quality)
            delivery.rollout.assert_called_once_with(self.run,'candidate','baseline',repo)
            self.runtime.board.review.assert_called_once()
            evidence=self.runtime.board.review.call_args.args[2]
            self.assertEqual(evidence['rollout'],'rollout')
            self.assertEqual(evidence['integrated'],'integrated')
        kb.complete_task.assert_not_called()

    def test_local_validation_waits_only_within_one_bounded_job_deadline(self):
        runner=object.__new__(IntegrationRunner);runner.project=self.runtime.project
        with patch('fabriquinha.runtime.Runner._execute',side_effect=[Pending('running'),'receipt']) as execute, \
             patch('fabriquinha.runtime.time.sleep'):
            self.assertEqual(runner._execute('current','exact','command'),'receipt')
        self.assertEqual(execute.call_count,2)
        with patch('fabriquinha.runtime.Runner._execute',side_effect=Pending('running')), \
             patch('fabriquinha.runtime.time.monotonic',side_effect=[0,136]):
            with self.assertRaises(EffectBlocked):runner._execute('current','exact','command')

    def test_qa_rechecks_exact_merge_ci_then_native_completion_not_release_homologation(self):
        from dataclasses import replace
        run=replace(self.run,number=8,actor='cto',reviewing=True)
        board=self.runtime.board=Mock();board.input.return_value='rollout'
        repo,github,quality=Mock(),Mock(),Mock()
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        kb=Mock();kb.get_task.return_value=SimpleNamespace(completion_contract='example/product')
        self.runtime.store=Mock()
        self.runtime.store.receipt.side_effect=[
            {'payload':{'candidate':'candidate'}},
            {'payload':{'integrated':'integrated','commit':'merge'}},
            {'payload':{'publication':'publication'}},
            {'payload':{'pr':'https://github.com/example/product/pull/1'}}]
        with patch('fabriquinha.runtime.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:conn),None)), \
             patch.object(self.runtime,'integration_services',return_value=(repo,github)), \
             patch('fabriquinha.runtime.Publication') as publication, \
             patch('fabriquinha.runtime.Deployment') as deployment:
            deployment.return_value.qa.return_value='qa-proof'
            result=self.runtime.integrate(run,quality)
            github.accept.assert_called_once_with('https://github.com/example/product/pull/1','merge')
            deployment.return_value.qa.assert_called_once_with(run,'rollout',repo)
            board.finish_review.assert_called_once()
            self.assertEqual(board.finish_review.call_args.args[2]['release_evidence'],'qa-proof')
            self.assertFalse(result['delivery_approval'])
            publication.return_value.publish.assert_not_called()


if __name__=='__main__':unittest.main()
