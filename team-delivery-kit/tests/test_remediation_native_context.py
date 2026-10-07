import copy
import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from execution_context import freeze,reference
from broker import remediation_native_context as publication


class RemediationNativeContextTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.row_factory=sqlite3.Row
        self.con.execute('CREATE TABLE remediation_executions(source_task TEXT,contract TEXT,state TEXT)')
        self.con.execute('CREATE TABLE native_bindings(issue_id TEXT,request_id TEXT)')
        self.con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        self.con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(dict(techlead='lead'))))
        @contextmanager
        def db():
            yield self.con;self.con.commit()
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock())
        capsule=freeze('Full approved product brief','Independent immutable review')
        self.runtime=dict(issue_id='issue',context_sha256=capsule['sha256'],
                          desired_issue_description=reference(capsule,'implementation'),
                          execution_authorized=False,dispatch_ready=False,release_homologated=False)
        self.value=dict(source_task='source',root_issue='root',run_id='run')
        self.state=dict(r1_runtime=self.runtime)
        self.desired=dict(id='issue',title='Recovery',description='Complete original card text',parent_issue_id='root',
                          project_id='project',stage=1,status='todo',assignee_id=None)
        self.issue=copy.deepcopy(self.desired);self.wakeups=[];self.writes=[]
        def put(key,body):
            self.writes.append(copy.deepcopy(body));self.issue.update({k:v for k,v in body.items() if k!='suppress_run'})
        self.fx=SimpleNamespace(get=lambda key:self.issue,wakeups=lambda key:self.wakeups,put=put)
        self.con.execute('INSERT INTO remediation_executions VALUES (?,?,?)',('source',json.dumps(self.value),json.dumps(self.state)))
        self.qualification=dict(issue_id='issue',parent_id='root',run_id='run',step='R1',
            context_sha256=capsule['sha256'],description=self.runtime['desired_issue_description'],
            expected_native=self.desired,runtime_sha256=publication.digest(self.runtime),execution_contract_sha256=publication.digest(self.value))

    def invoke(self,now=100):
        with patch.object(publication,'qualify',return_value=self.qualification),patch.object(publication,'Effects',return_value=self.fx):
            return publication.publish(self.b,'source','R1',now=now)

    def test_fixed_description_projection_keeps_unassigned_todo_and_no_execution_grant(self):
        receipt=self.invoke()
        self.assertEqual(receipt['stage'],'published');self.assertFalse(receipt['execution_authorized'])
        self.assertEqual(self.writes,[dict(description=self.runtime['desired_issue_description'],suppress_run=True)])
        self.assertEqual(self.issue['status'],'todo');self.assertIsNone(self.issue['assignee_id'])
        self.assertEqual(self.invoke(),receipt);self.assertEqual(len(self.writes),1)

    def test_lost_put_ack_is_reconciled_without_repeated_write(self):
        put=self.fx.put
        def lost(key,body):put(key,body);raise TimeoutError()
        self.fx.put=lost
        with self.assertRaises(TimeoutError):self.invoke()
        self.fx.put=put
        self.assertEqual(self.invoke()['stage'],'published');self.assertEqual(len(self.writes),1)

    def test_restart_before_put_is_observation_only_not_new_permission(self):
        self.fx.put=lambda *args:(_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.invoke()
        self.fx.put=lambda *args:self.writes.append(args)
        self.assertEqual(self.invoke(now=200)['stage'],'observing')
        self.assertEqual(self.writes,[])

    def test_no_effect_uncertain_write_has_visible_bounded_hold(self):
        self.fx.put=lambda *args:(_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(TimeoutError):self.invoke()
        self.assertEqual(self.invoke(now=701)['stage'],'observing')
        self.assertTrue(self.invoke(now=701)['alert'])
        self.assertEqual(self.invoke(now=1901)['stage'],'blocked');self.assertEqual(self.writes,[])
        self.assertEqual(self.invoke(now=2000)['stage'],'blocked')

    def test_native_drift_assignment_enabled_wakeup_and_own_lease_reject_before_put(self):
        for change in (dict(assignee_id='actor'),dict(status='done'),dict(parent_issue_id='other'),dict(description='unrelated')):
            self.issue={**self.desired,**change}
            with self.assertRaises(ValueError):self.invoke()
            self.assertEqual(self.writes,[])
        self.issue=copy.deepcopy(self.desired);self.wakeups=[dict(enabled=True)]
        with self.assertRaises(ValueError):self.invoke()
        self.wakeups=[]
        self.con.execute('INSERT INTO leases VALUES (?,?)',('busy','running'))
        self.con.execute('INSERT INTO native_bindings VALUES (?,?)',('issue','busy'))
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.writes,[])

    def test_unrelated_lease_does_not_starve_presentation(self):
        self.con.execute('INSERT INTO leases VALUES (?,?)',('other','running'))
        self.con.execute('INSERT INTO native_bindings VALUES (?,?)',('other-issue','other'))
        self.assertEqual(self.invoke()['stage'],'published')

    def test_changed_context_after_published_receipt_is_not_accepted(self):
        self.invoke();self.qualification['context_sha256']='0'*64
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(len(self.writes),1)

    def test_written_reference_without_durable_intent_is_not_adopted(self):
        self.issue['description']=self.runtime['desired_issue_description']
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.writes,[])

    def test_real_r2_qualification_binds_paused_route_runtime_and_foreign_red(self):
        import test_remediation_product_context as fixtures
        f=fixtures.RemediationProductContextTests();f.setUp();self.addCleanup(f.doCleanups)
        runtime=f.invoke()
        fx=SimpleNamespace(get=lambda key:f.f.f.parent,native=SimpleNamespace())
        with patch.object(publication.review,'verify'):
            qualified=publication.qualify(f.b,'source','R2',fx)
        self.assertEqual(qualified['context_sha256'],runtime['context_sha256'])
        self.assertEqual(qualified['runtime_sha256'],publication.digest(runtime))
        with f.b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(runtime['issue_id'],)).fetchone()[0])
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps({**route,'enabled':True}),runtime['issue_id']))
        with self.assertRaises(ValueError):publication.qualify(f.b,'source','R2',fx)

    def test_watchdog_publishes_once_without_assignment_or_wakeup(self):
        with patch.object(publication,'qualify',return_value=self.qualification),patch.object(publication,'Effects',return_value=self.fx):
            publication.tick(self.b);publication.tick(self.b)
        self.assertEqual(len(self.writes),1);self.assertIsNone(self.issue['assignee_id'])

    def test_before_intent_transport_failure_has_deadline_and_technical_owner(self):
        state={**self.state,'native_context_observations':{'R1':dict(started_at=0,execution_authorized=False)}}
        self.con.execute('UPDATE remediation_executions SET state=?',(json.dumps(state),))
        publication.tick(self.b)
        state=json.loads(self.con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.assertEqual(state['native_context_hold']['owner'],'lead')
        self.assertEqual(state['native_context_hold']['category'],'native_context_observation_deadline')
        self.assertEqual(self.writes,[])

    def test_http_permission_rejection_is_not_an_infinite_transport_retry(self):
        import urllib.error
        error=urllib.error.HTTPError('http://synthetic',403,'forbidden',{},None)
        with patch.object(publication,'qualify',side_effect=error),patch.object(publication,'Effects',return_value=self.fx):
            publication.tick(self.b);publication.tick(self.b)
        state=json.loads(self.con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.assertEqual(state['native_context_hold']['category'],'native_context_http_rejected')
        self.assertEqual(state['native_context_hold']['owner'],'lead');self.assertEqual(self.writes,[])
