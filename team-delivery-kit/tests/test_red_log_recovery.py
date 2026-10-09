import copy
from contextlib import contextmanager
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from broker import handoffs
from broker.red_log_recovery import eligible,reconcile

TASK='22222222-2222-4222-8222-222222222222'


class RedLogRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        @contextmanager
        def db():
            with self.con:yield self.con
        self.b=SimpleNamespace(db=db)
        self.con.execute('CREATE TABLE test_first_jobs(job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        handoffs.initialize(self.con)
        self.source=dict(id=TASK,status='completed');self.route=dict(issue_id='issue',cto='cto')
        self.prior=dict(stage='technical_decision_required',data=json.dumps(dict(phase='test_first',error='RuntimeError:validator output unavailable')))
        self.job=dict(identity=json.dumps(dict(name='delivery-kit-test-red-v2-'+TASK,
            payload=dict(Labels={'delivery-kit.test-first-task':TASK}))),
            state=json.dumps(dict(stage='start_intent',container_id='container')))
        self.con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',(TASK+':red',self.job['identity'],self.job['state']))
        self.con.commit()

    def test_exact_log_failure_recaptures_same_job_and_records_no_execution_authority(self):
        effects=SimpleNamespace(capture_test_first_red=Mock(return_value=dict(task_id=TASK,issue_id='issue',red={'output_sha256':'a'*64})))
        self.assertTrue(reconcile(self.b,self.route,self.source,self.prior,effects))
        receipt=json.loads(self.con.execute('SELECT receipt FROM red_log_recoveries').fetchone()[0])
        self.assertEqual(receipt['container_id'],'container')
        self.assertEqual(receipt['stage'],'complete')
        for key in ('author_restarted','tests_reexecuted','delivery_approval'):self.assertFalse(receipt[key])
        self.assertEqual(handoffs.load(self.con,TASK)['stage'],'test_first_red_captured')
        self.assertTrue(reconcile(self.b,self.route,self.source,self.prior,effects))
        effects.capture_test_first_red.assert_called_once_with({'task_id':TASK})

    def test_changed_identity_other_failure_or_unstarted_job_cannot_recover(self):
        for field,value in [('phase','implementation'),('error','RuntimeError:other')]:
            prior=copy.deepcopy(self.prior);data=json.loads(prior['data']);data[field]=value;prior['data']=json.dumps(data)
            self.assertFalse(eligible(self.source,prior,self.job))
        self.assertFalse(eligible(dict(self.source,status='running'),self.prior,self.job))
        changed=dict(self.job,state=json.dumps(dict(stage='create_intent',container_id='container')))
        self.assertFalse(eligible(self.source,self.prior,changed))

    def test_failure_stays_blocked_without_identical_retry(self):
        effects=SimpleNamespace(capture_test_first_red=Mock(side_effect=ValueError('invalid Red')))
        self.assertTrue(reconcile(self.b,self.route,self.source,self.prior,effects))
        self.assertTrue(reconcile(self.b,self.route,self.source,self.prior,effects))
        effects.capture_test_first_red.assert_called_once()
        self.assertEqual(json.loads(self.con.execute('SELECT receipt FROM red_log_recoveries').fetchone()[0])['stage'],'blocked')
