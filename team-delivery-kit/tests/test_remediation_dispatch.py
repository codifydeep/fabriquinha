import copy
import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import remediation_dispatch as dispatcher


class RemediationDispatchTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close);self.con.row_factory=sqlite3.Row
        @contextmanager
        def db():yield self.con;self.con.commit()
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock())
        self.binding=dict(issue_id='issue',author='author',owner='lead',enabled=True,minimum_calls=8,
            context_sha256='a'*64,execution_contract_sha256='b'*64,native_context_sha256='c'*64,
            description='DELIVERY_EXECUTION_CONTEXT_V1:'+'a'*64+':implementation',source_task='source',step='R1')
        self.calls=[];self.tasks=[];self.remaining=100;self.available=True
        self.issue=dict(id='issue',status='todo',assignee_id=None,description=self.binding['description'])
        def wake(*args,allow_create):
            self.calls.append(allow_create);return dict(id='wake')
        self.fx=SimpleNamespace(wake=wake,runs=lambda issue:self.tasks,issue=lambda issue:self.issue,
            remaining_calls=lambda:self.remaining,available=lambda *args:self.available)

    def invoke(self,now=100):
        with patch.object(dispatcher,'binding',return_value=self.binding),patch.object(dispatcher,'Effects',return_value=self.fx):
            return dispatcher.dispatch(self.b,'source','R1',now=now)

    def test_one_durable_wakeup_and_exact_task_acceptance(self):
        result=self.invoke();self.assertEqual(result['stage'],'awaiting_acceptance');self.assertEqual(self.calls,[True])
        self.tasks=[dict(id='task',issue_id='issue',agent_id='author',wakeup_id='wake',status='running')]
        receipt=self.invoke(now=120);self.assertEqual(receipt['stage'],'accepted');self.assertEqual(receipt['task_id'],'task')
        self.assertEqual(self.invoke(now=200),receipt);self.assertEqual(self.calls,[True])
        self.assertFalse(receipt['release_homologated'])

    def test_lost_ack_observes_same_wakeup_without_repeated_post(self):
        def wake(*args,allow_create):
            self.calls.append(allow_create)
            if allow_create:raise TimeoutError()
            return dict(id='wake')
        self.fx.wake=wake
        with self.assertRaises(TimeoutError):self.invoke()
        self.assertEqual(self.invoke(now=120)['stage'],'awaiting_acceptance')
        self.assertEqual(self.calls,[True,False])

    def test_restart_before_post_does_not_recreate_missing_handle(self):
        def wake(*args,allow_create):
            self.calls.append(allow_create)
            if allow_create:raise KeyboardInterrupt()
            return None
        self.fx.wake=wake
        with self.assertRaises(KeyboardInterrupt):self.invoke()
        self.assertEqual(self.invoke(now=120)['stage'],'write_observe');self.assertEqual(self.calls,[True,False])
        self.assertTrue(self.invoke(now=701)['alert']);self.assertEqual(self.calls,[True,False,False])

    def test_existing_wakeup_observation_does_not_require_new_budget(self):
        self.invoke();self.remaining=0
        self.tasks=[dict(id='task',issue_id='issue',agent_id='author',wakeup_id='wake',status='completed')]
        self.assertEqual(self.invoke()['stage'],'accepted');self.assertEqual(self.calls,[True])

    def test_budget_capacity_and_paused_route_never_post(self):
        self.remaining=0;self.assertEqual(self.invoke()['stage'],'budget_wait');self.assertEqual(self.calls,[])
        self.remaining=100;self.available=False
        self.assertEqual(self.invoke(now=120)['stage'],'capacity_wait');self.assertEqual(self.calls,[])
        self.binding['enabled']=False
        self.assertEqual(self.invoke(now=140)['stage'],'paused');self.assertEqual(self.calls,[])

    def test_unattended_acceptance_is_retained_not_retried(self):
        self.invoke();self.assertTrue(self.invoke(now=701)['alert']);result=self.invoke(now=1901)
        self.assertEqual(result['stage'],'blocked');self.assertEqual(result['owner'],'lead')
        self.assertEqual(self.invoke(now=2000),result);self.assertEqual(self.calls,[True])

    def test_wrong_or_duplicate_task_identity_does_not_count_as_acceptance(self):
        self.invoke()
        for tasks in ([dict(id='wrong',issue_id='other',agent_id='author',wakeup_id='wake',status='running')],
                      [dict(id='task',issue_id='issue',agent_id='wrong',wakeup_id='wake',status='running')],
                      [dict(id=str(i),issue_id='issue',agent_id='author',wakeup_id='wake',status='running') for i in range(2)]):
            self.tasks=tasks
            with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[True])

    def test_changed_context_cannot_rebind_existing_intent(self):
        self.invoke();self.binding['context_sha256']='0'*64
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[True])

    def test_failed_task_is_visible_without_identical_author_restart(self):
        self.invoke();self.tasks=[dict(id='task',issue_id='issue',agent_id='author',wakeup_id='wake',status='failed')]
        receipt=self.invoke();self.assertEqual(receipt['stage'],'blocked');self.assertEqual(receipt['category'],'author_execution_failed')
        self.assertEqual(self.invoke(),receipt);self.assertEqual(self.calls,[True])

    def test_operator_pause_after_uncertain_post_does_not_prevent_readonly_observation(self):
        self.invoke();self.binding['enabled']=False
        self.tasks=[dict(id='task',issue_id='issue',agent_id='author',wakeup_id='wake',status='completed')]
        self.assertEqual(self.invoke()['stage'],'accepted');self.assertEqual(self.calls,[True])

    def test_real_capacity_counts_two_slots_one_profile_and_unresolved_reservation(self):
        self.con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        self.con.execute('CREATE TABLE native_bindings(request_id TEXT,issue_id TEXT,agent_id TEXT)')
        dispatcher.initialize(self.con)
        fx=dispatcher.Effects.__new__(dispatcher.Effects);fx.b=self.b
        self.assertTrue(fx.available('issue','author'))
        self.con.execute('INSERT INTO leases VALUES (?,?)',('lease','running'))
        self.con.execute('INSERT INTO native_bindings VALUES (?,?,?)',('lease','other','author'))
        self.assertFalse(fx.available('issue','author'))
        self.assertTrue(fx.available('issue','different-author'))
        other={**self.binding,'issue_id':'pending','author':'different-author'}
        self.con.execute('INSERT INTO remediation_dispatches VALUES (?,?,?,?,?)',('other-source','R1','marker',json.dumps(other),
            json.dumps(dict(post_attempted=True,stage='write_observe'))))
        self.assertFalse(fx.available('issue','third-author'))
        self.con.execute("UPDATE native_bindings SET issue_id='pending',agent_id='different-author'")
        self.assertTrue(fx.available('issue','third-author'))  # Same reservation and lease are not counted twice.

    def test_real_published_r2_binding_is_product_only_and_paused_until_separate_activation(self):
        import test_remediation_product_context as fixtures
        from broker import remediation_native_context as publication
        f=fixtures.RemediationProductContextTests();f.setUp();self.addCleanup(f.doCleanups)
        runtime=f.invoke();fx=SimpleNamespace(get=lambda key:f.f.f.parent,native=SimpleNamespace())
        with patch.object(publication.review,'verify'):
            intent=publication.qualify(f.b,'source','R2',fx)
        with f.b.db() as con:
            publication.initialize(con)
            con.execute('INSERT INTO remediation_native_contexts VALUES (?,?,?,?)',('source','R2',json.dumps(intent),
                json.dumps(dict(stage='published',context_sha256=runtime['context_sha256'],runtime_sha256=publication.digest(runtime)))))
        with patch.object(dispatcher.review,'verify'):
            bound=dispatcher.binding(f.b,'source','R2',fx)
        self.assertFalse(bound['enabled']);self.assertEqual(bound['context_sha256'],runtime['context_sha256'])
        with f.b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(runtime['issue_id'],)).fetchone()[0])
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps({**route,'enabled':True}),runtime['issue_id']))
        with patch.object(dispatcher.review,'verify'):
            self.assertTrue(dispatcher.binding(f.b,'source','R2',fx)['enabled'])

    def test_watchdog_tracks_before_intent_wait_only_after_route_is_enabled(self):
        self.con.execute('CREATE TABLE remediation_executions(source_task TEXT,state TEXT)')
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        self.con.execute('INSERT INTO remediation_executions VALUES (?,?)',('source',json.dumps(dict(r1_runtime=dict(issue_id='issue')))))
        self.con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(dict(enabled=False,techlead='lead'))))
        dispatcher.tick(self.b)
        self.assertEqual(self.con.execute('SELECT count(*) FROM remediation_dispatch_observations').fetchone()[0],0)
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(dict(enabled=True,techlead='lead')),))
        with patch.object(dispatcher,'dispatch',side_effect=TimeoutError()):dispatcher.tick(self.b)
        self.assertEqual(self.con.execute('SELECT count(*) FROM remediation_dispatch_observations').fetchone()[0],1)
        self.con.execute('UPDATE remediation_dispatch_observations SET started_at=0')
        dispatcher.tick(self.b)
        hold=json.loads(self.con.execute('SELECT data FROM remediation_dispatch_holds').fetchone()[0])
        self.assertEqual(hold['owner'],'lead');self.assertEqual(hold['category'],'dispatch_observation_deadline')
        self.assertEqual(self.calls,[])
