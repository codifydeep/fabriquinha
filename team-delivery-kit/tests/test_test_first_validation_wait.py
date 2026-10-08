import json
import unittest
from unittest.mock import patch
from broker import test_first_handoffs as h
import test_test_first_handoffs as fixtures


class ValidationWaitTests(unittest.TestCase):
    setUp=fixtures.TestFirstHandoffTests.setUp
    tearDown=fixtures.TestFirstHandoffTests.tearDown
    def test_pending_lease_does_not_capture_red_dispatch_or_create_incident(self):
        self.effects.test_source_finalization=lambda *_:'pending'
        task={**self.test_task,'status':'completed'}
        self.assertIsNone(h.reconcile(self.broker,self.route,[task],self.effects))
        self.assertEqual(self.effects.calls,0)
        self.assertEqual(self.effects.wakeups,[])
        with self.broker.db() as c:
            state=h.handoffs.load(c,'tests');self.assertEqual(state['stage'],'test_first_validation_pending')
            self.assertEqual(json.loads(state['data'])['validation_wait']['category'],'lease_finalization')

    def test_pending_fixed_job_is_observed_again_not_sent_to_cto(self):
        self.effects.test_source_finalization=lambda *_:'ready'
        calls=[]
        def pending(payload):calls.append(payload);raise TimeoutError('test-first job pending; observe existing execution')
        self.effects.capture_test_first_red=pending
        task={**self.test_task,'status':'completed'}
        for _ in range(2):self.assertIsNone(h.reconcile(self.broker,self.route,[task],self.effects))
        self.assertEqual(calls,[{'task_id':'tests'}]*2)
        self.assertEqual(self.effects.wakeups,[])
        with self.broker.db() as c:self.assertEqual(h.handoffs.load(c,'tests')['stage'],'test_first_validation_pending')

    def test_readiness_then_red_uses_same_task_without_author_retry(self):
        self.effects.test_source_finalization=lambda *_:'pending'
        task={**self.test_task,'status':'completed'}
        h.reconcile(self.broker,self.route,[task],self.effects)
        self.effects.test_source_finalization=lambda *_:'ready'
        h.reconcile(self.broker,self.route,[task],self.effects)
        self.assertEqual(self.effects.calls,1);self.assertEqual(self.effects.wakeups,[])

    def test_wait_deadline_stays_visible_without_new_author_or_cto_execution(self):
        self.effects.test_source_finalization=lambda *_:'pending'
        with patch('broker.test_first_handoffs.time.time',return_value=0):
            h.reconcile(self.broker,self.route,[self.test_task],self.effects)
        with patch('broker.test_first_handoffs.time.time',return_value=601):
            h.reconcile(self.broker,self.route,[self.test_task],self.effects)
        with self.broker.db() as c:
            row=h.handoffs.load(c,'tests');self.assertEqual(row['stage'],'test_first_blocked')
            self.assertEqual(json.loads(row['data'])['error'],'test_first_validation_observation_deadline')
        self.assertEqual(self.effects.wakeups,[]);self.assertEqual(self.effects.calls,0)

    def test_real_finalization_query_is_closed_implementation_only(self):
        from broker.handoff_runtime import Effects
        with self.broker.db() as c:
            c.executescript("CREATE TABLE native_bindings(task_id TEXT,request_id TEXT,issue_id TEXT,agent_id TEXT);"
                "CREATE TABLE grants(request_id TEXT,mode TEXT,attempt INTEGER);"
                "CREATE TABLE leases(request_id TEXT,status TEXT);"
                "INSERT INTO native_bindings VALUES('tests','request','issue','author');"
                "INSERT INTO grants VALUES('request','implementation',1);"
                "INSERT INTO leases VALUES('request','closing');")
        effects=Effects(self.broker,{})
        self.assertEqual(effects.test_source_finalization('issue','tests'),'pending')
        with self.broker.db() as c:c.execute("UPDATE leases SET status='closed'")
        self.assertEqual(effects.test_source_finalization('issue','tests'),'ready')
        with self.broker.db() as c:c.execute("UPDATE grants SET mode='planning'")
        with self.assertRaises(ValueError):effects.test_source_finalization('issue','tests')
