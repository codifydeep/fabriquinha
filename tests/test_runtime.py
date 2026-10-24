"""Operational adapter keeps lifecycle native and credentials out of workers' argv."""
import json
import os
from contextlib import closing
from pathlib import Path
import sys
import sqlite3
import threading
from contextlib import nullcontext, contextmanager
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import write_json, EffectBlocked
from fabriquinha.hermes import Sandbox
from fabriquinha.runtime import Runtime, Owner, model_route
from fabriquinha.operations import ActivityPaused
from test_delivery_core import configuration


class NativeRuntime(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        write_json(self.root/'project.json',configuration())
        with patch('fabriquinha.runtime.bind'):
            self.runtime=Runtime(self.root,self.root/'upstream')

    def test_only_one_continuous_owner_and_shutdown_does_not_kill_workers(self):
        with Owner(self.root):
            with self.assertRaises(BlockingIOError):
                with Owner(self.root):pass
        with Owner(self.root):pass
        self.assertEqual(self.runtime.children,[])

    def test_native_connection_lifetime_covers_service_and_worker_without_a_write_transaction(self):
        self.assertTrue(hasattr(Runtime,'_serve'))
        self.assertTrue(hasattr(Runtime,'_worker'))
        held=[];connection=Mock()
        @contextmanager
        def connect():
            held.append(True)
            try:yield connection
            finally:held.pop()
        def active(*args,**kwargs):
            self.assertEqual(held,[True]);return 'active'
        api=SimpleNamespace(connect_closing=connect)
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)), \
             patch.object(self.runtime,'_serve',side_effect=active),patch.object(self.runtime,'_worker',side_effect=active):
            self.assertEqual(self.runtime.serve(threading.Event()),'active')
            self.assertEqual(held,[])
            self.assertEqual(self.runtime.worker('card',1),'active')
            self.assertEqual(held,[])
        self.assertTrue(all(call.args[0]=='SELECT id FROM tasks LIMIT 1' for call in connection.execute.call_args_list))

    def test_graceful_shutdown_refreshes_final_notification_status(self):
        stop=threading.Event();stop.set()
        api=SimpleNamespace(connect_closing=lambda:nullcontext(Mock()))
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)), \
             patch('fabriquinha.runtime.model_route'),patch.object(self.runtime.outbox,'capture'), \
             patch.object(self.runtime,'status',return_value={'notifications':{'delivered':21,'queued':0}}):
            self.runtime.serve(stop,interval=0.1)
        result=json.loads((self.root/'status.json').read_bytes())
        self.assertEqual(result['dispatcher_state'],'stopped')
        self.assertEqual(result['board']['notifications'],{'delivered':21,'queued':0})

    def test_outbox_scope_error_disables_sender_not_native_dispatch(self):
        stop=threading.Event();api=SimpleNamespace(connect_closing=lambda:nullcontext(Mock()))
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)), \
             patch('fabriquinha.runtime.model_route'), \
             patch.object(self.runtime.outbox,'capture',side_effect=ValueError('board history changed')), \
             patch.object(self.runtime,'status',return_value={'cards':[]}), \
             patch.object(self.runtime,'tick',side_effect=lambda:stop.set()) as tick:
            self.runtime.serve(stop,interval=0.1)
        tick.assert_called_once()
        error=json.loads((self.runtime.outbox.root/'error.json').read_bytes())
        self.assertEqual(error['category'],'ValueError')

    def test_status_uses_native_event_and_heartbeat_fields_not_an_invented_updated_column(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        conn.executescript('CREATE TABLE tasks(id,title,status,assignee,current_run_id,last_heartbeat_at,created_at,body);'
            'CREATE TABLE task_runs(id,started_at);'
            'CREATE TABLE task_events(task_id,created_at);'
            "INSERT INTO tasks VALUES('t1','Work','running','backend',7,300,100,'{}');"
            "INSERT INTO task_runs VALUES(7,150);"
            "INSERT INTO task_events VALUES('t1',200);")
        api=SimpleNamespace(connect_closing=lambda:closing(conn))
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)):
            status=self.runtime.status()
        card=status['cards'][0]
        self.assertEqual((card['last_event_at'],card['last_heartbeat_at']),(200,300))
        self.assertFalse(status['delivery_approval'])

    def test_model_route_is_private_loopback_and_does_not_release_paid_provider(self):
        route=dict(base_url='http://127.0.0.1:12345/v1',api_key='fixture-only',provider='custom',
                   api_mode='chat_completions',model='local-fixture')
        path=self.root/'route.json';write_json(path,route)
        self.assertEqual(model_route(self.runtime.project,path),route)
        path.chmod(0o644)
        with self.assertRaises(ValueError):model_route(self.runtime.project,path)
        path.chmod(0o600)
        other=configuration();other['qualification']=False
        with self.assertRaises(ValueError):model_route(Project.parse(other),path)
        route['base_url']='https://example.com/v1';write_json(path,route)
        with self.assertRaises(ValueError):model_route(self.runtime.project,path)

    def test_spawn_uses_fixed_worker_command_without_inherited_provider_keys(self):
        task=SimpleNamespace(id='task',current_run_id=7,assignee='backend')
        with patch.dict(os.environ,GH_TOKEN='must-not-inherit',OPENROUTER_API_KEY='must-not-inherit'), \
             patch.object(self.runtime,'check_admission',return_value=dict(ready=True,missing_profiles=[])), \
             patch.object(self.runtime,'settle'), \
             patch('fabriquinha.runtime.subprocess.Popen') as popen:
            popen.return_value.pid=42
            self.assertEqual(self.runtime.spawn(task,'/unused'),42)
            args,kwargs=popen.call_args
            self.assertEqual(args[0][1:4],['-m','fabriquinha.runtime','worker'])
            self.assertNotIn('GH_TOKEN',kwargs['env'])
            self.assertNotIn('OPENROUTER_API_KEY',kwargs['env'])
            self.assertNotIn('route.json',args[0])
            self.assertTrue(kwargs['start_new_session'])
            self.assertEqual((self.root/'runs/7/worker.log').stat().st_mode & 0o777,0o600)

    def test_spawning_other_work_does_not_hide_an_unsettled_task(self):
        self.runtime.settlement={'older':dict(run=1,category='EffectBlocked')}
        self.runtime.settle('different',conn=Mock())
        self.assertIn('older',self.runtime.settlement)

    def test_cached_missing_profile_cannot_refuse_a_fresh_native_dispatch(self):
        task=SimpleNamespace(id='task',current_run_id=7,assignee='backend')
        modules={'tools':SimpleNamespace(),'tools.process_registry':SimpleNamespace(RestartSafeScopeUnavailable=EffectBlocked)}
        with patch.dict(sys.modules,modules), \
             patch.object(self.runtime,'check_admission',return_value=dict(ready=True,missing_profiles=['backend'])), \
             patch.object(self.runtime,'settle'),patch.object(self.runtime,'_spawn',return_value=42):
            self.assertEqual(self.runtime.spawn(task,'/unused'),42)

    def test_invalid_graph_defers_only_that_spawn_before_any_model_worker(self):
        value=configuration();value.update(coordination_roles={'product':'product','lead':'lead'},
            delivery_roles={'tests':'qa','integration':'devops'},browser_image='sha256:'+'b'*64,
            reviewers={'backend':'lead','lead':'cto','qa':'lead','devops':'qa'})
        self.runtime.project=Project.parse(value);self.runtime.releases=Mock()
        task=SimpleNamespace(id='work',current_run_id=7,assignee='backend')
        modules={'tools':SimpleNamespace(),'tools.process_registry':SimpleNamespace(RestartSafeScopeUnavailable=EffectBlocked)}
        with patch.dict(sys.modules,modules),patch.object(self.runtime,'check_admission',return_value={'ready':True}), \
             patch.object(self.runtime,'settle'),patch.object(self.runtime,'_spawn',return_value=42) as spawn:
            self.runtime.releases.admit.side_effect=ValueError('invalid graph')
            with self.assertRaises(EffectBlocked):self.runtime.spawn(task,'/unused')
            spawn.assert_not_called();self.assertFalse(self.runtime.control.read()['paused'])
            self.runtime.releases.admit.side_effect=None
            self.assertEqual(self.runtime.spawn(SimpleNamespace(id='diagnosis'),'/unused'),42)

    def test_second_process_cannot_adopt_an_already_owned_run_or_block_its_owner(self):
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        conn.execute.return_value.fetchone.return_value={'worker_pid':os.getpid()+1000000}
        api=SimpleNamespace(connect_closing=lambda:conn)
        kb=Mock();dispatcher=Mock();dispatcher.adopt_worker_pid.return_value=True
        self.runtime.board=Mock();self.runtime.board.current.side_effect=AssertionError('duplicate reached controller authority')
        with patch('fabriquinha.runtime.native',return_value=(kb,api,dispatcher)):
            with self.assertRaisesRegex(ValueError,'another worker'):self.runtime.worker('task',7)
        kb.block_task.assert_not_called();kb.build_worker_context.assert_not_called()

    def test_orphan_reconstruction_is_retirement_only_and_project_bound(self):
        project=self.runtime.project
        run=Run('task',2,'backend','tests',False,'backend','v1','contract')
        expected=dict(binding=run.binding(),project=project.fingerprint(),workspace=str(self.root/'work'),
                      phase='tests',baseline_tests=[],image=project.validation_image)
        sandbox=Sandbox.recover(project,self.runtime.store,expected)
        self.assertTrue(sandbox.closing)
        with self.assertRaises(ValueError):sandbox.start()
        expected['project']='different-installation'
        with self.assertRaises(ValueError):Sandbox.recover(project,self.runtime.store,expected)

    def test_recovery_does_not_retire_sandbox_of_a_live_worker(self):
        run=Run('task',2,'backend','tests',False,'backend','v1','contract')
        expected=dict(binding=run.binding(),project=self.runtime.project.fingerprint(),workspace=str(self.root/'work'),
                      phase='tests',baseline_tests=[],image=self.runtime.project.validation_image)
        from fabriquinha.artifacts import digest
        key=digest(expected)
        write_json(self.runtime.store.root/'effects'/(digest(key+':agent-create')+'.json'),
                   dict(identity=expected,state='intent'))
        row=dict(id=2,task_id='task',profile='backend',worker_pid=123,worker_started_at='verified',
                 claim_lock='local',ended_at=100)
        conn=Mock();conn.execute.return_value.fetchone.return_value=row
        with patch('fabriquinha.runtime.worker_alive',return_value=True), \
             patch.object(Sandbox,'recover') as recover:
            with self.assertRaises(EffectBlocked):self.runtime.settle('task',conn=conn)
        recover.assert_not_called()
        with patch('fabriquinha.runtime.worker_alive',return_value=False), \
             patch.object(Sandbox,'recover') as recover:
            self.runtime.settle('task',conn=conn)
        recover.return_value.close.assert_called_once()

    def test_pause_fences_even_direct_delivery_handlers_before_native_state_access(self):
        self.runtime.control.pause()
        with patch.object(self.runtime.board,'current',side_effect=AssertionError('gate crossed pause')):
            with self.assertRaises(ActivityPaused):self.runtime.board.ensure(Mock())

    def test_paused_tick_does_not_dispatch_diagnose_or_probe_model_resources(self):
        self.runtime.control.pause();conn=Mock()
        api=SimpleNamespace(connect_closing=lambda:nullcontext(conn));dispatcher=Mock()
        with patch('fabriquinha.runtime.native',return_value=(None,api,dispatcher)), \
             patch.object(self.runtime,'maintain_pause') as maintenance, \
             patch.object(self.runtime,'check_admission') as admission, \
             patch.object(self.runtime.recovery,'reconcile') as recovery:
            self.runtime.tick()
        maintenance.assert_called_once_with(conn)
        admission.assert_not_called();recovery.assert_not_called();dispatcher.dispatch_once.assert_not_called()

    def test_failed_admission_allows_native_reconciliation_but_no_new_workers(self):
        api=SimpleNamespace(connect_closing=lambda:nullcontext(Mock()));dispatcher=Mock()
        with patch('fabriquinha.runtime.native',return_value=(None,api,dispatcher)), \
             patch.object(self.runtime,'settle'),patch.object(self.runtime,'wake_integrations'), \
             patch.object(self.runtime.recovery,'reconcile'), \
             patch.object(self.runtime,'check_admission',return_value=dict(ready=False,missing_profiles=[])):
            self.runtime.tick()
        self.assertEqual(dispatcher.dispatch_once.call_args.kwargs['max_spawn'],0)

    def test_pause_reclaims_only_after_verified_death_and_retains_native_phase_handling(self):
        marker=self.runtime.control.pause();conn=Mock();kb=Mock()
        row=dict(id=7,task_id='task',worker_pid=123,worker_started_at='fp',claim_lock='local')
        conn.execute.return_value.fetchall.return_value=[row]
        kb.get_task.return_value=SimpleNamespace(id='task',status='running',current_run_id=7)
        with patch('fabriquinha.runtime.native',return_value=(kb,None,None)), \
             patch('fabriquinha.runtime.worker_alive',return_value=True),patch.object(self.runtime,'settle'):
            self.runtime.maintain_pause(conn)
        kb.reclaim_task.assert_not_called()
        with patch('fabriquinha.runtime.native',return_value=(kb,None,None)), \
             patch('fabriquinha.runtime.worker_alive',return_value=False),patch.object(self.runtime,'settle'):
            self.runtime.maintain_pause(conn)
        kb.reclaim_task.assert_called_once_with(conn,'task',reason='operator_pause:'+marker['episode'])

    def test_invalid_control_is_a_fence_not_an_operator_reclaim_authority(self):
        self.runtime.control.pause();(self.root/'control.json').write_text('corrupt')
        conn=Mock();kb=Mock()
        with patch('fabriquinha.runtime.native',return_value=(kb,None,None)),patch.object(self.runtime,'settle') as settle:
            self.runtime.maintain_pause(conn)
        conn.execute.assert_not_called();kb.reclaim_task.assert_not_called();settle.assert_not_called()

    def test_resume_refuses_busy_workers_and_does_not_clear_provider_gate(self):
        episode=self.runtime.control.pause()['episode']
        api=SimpleNamespace(connect_closing=lambda:nullcontext(Mock()))
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)), \
             patch.object(self.runtime,'maintain_pause'), \
             patch.object(self.runtime,'pause_status',return_value=dict(agents_stopped=False)), \
             patch('fabriquinha.runtime.model_route') as route:
            with self.assertRaises(EffectBlocked):self.runtime.resume(episode)
        route.assert_not_called();self.assertTrue(self.runtime.control.read()['paused'])
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)), \
             patch.object(self.runtime,'maintain_pause'), \
             patch.object(self.runtime,'pause_status',return_value=dict(agents_stopped=True,pending_effects=['original'])), \
             patch.object(self.runtime,'check_admission',return_value=dict(ready=True)), \
             patch('fabriquinha.runtime.model_route',side_effect=ValueError('provider pause')):
            with self.assertRaises(ValueError):self.runtime.resume(episode)
        self.assertTrue(self.runtime.control.read()['paused'])
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)), \
             patch.object(self.runtime,'maintain_pause'), \
             patch.object(self.runtime,'pause_status',return_value=dict(agents_stopped=True,pending_effects=['original'])), \
             patch.object(self.runtime,'check_admission',return_value=dict(ready=True)), \
             patch('fabriquinha.runtime.model_route'):
            result=self.runtime.resume(episode)
        self.assertEqual(result['pending_effects'],['original'])
        self.assertFalse(self.runtime.control.read()['paused'])


if __name__=='__main__':unittest.main()
