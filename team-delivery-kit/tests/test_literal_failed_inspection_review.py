import hashlib
import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from generic_harness_calibration import digest
from broker import literal_failed_inspection_review as review
import review_failed_literal_inspection as cli


class FailedInspectionReviewTests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='delivery-kit-port2-broker-v1')
        self.cfg=dict(source=dict(author_task='original',issue_id='parent',candidate_volume='frozen-original',
            prepared=dict(manifest_sha256='a'*64)),author='author',reviewer='lead',cto='cto',image='sha256:'+'b'*64,
            test_path='tests/test.py',literal='NODE_HARNESS',counterexample={'facts':{'assertion_bindings':
                dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11')}})
        self.inspection=dict(candidate_manifest_sha256='c'*64,stale_witness_selectivity_passed=False,
            reports={'guarded':dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #11'),
                'unguarded':dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #4')})
        self.s=dict(stage='blocked',category='maintenance_sensitivity_failed',issue_id='child',author_task='delivered',
            author_wakeup='author-wake',revision=0,history=[],decisions={p:{} for p in ('triage','plan','permit')},
            snapshot=dict(task_id='delivered',volume='frozen-delivered',status='complete'),inspection=self.inspection,
            source_reset=False,functional_red=False,delivery_approval=False)
        self.author=dict(id='delivered',agent_id='author',issue_id='child',status='completed',wakeup_id='author-wake')
        self.binding=dict(task_id='delivered',agent_id='author',issue_id='child',status='closed',scope='workspace:implementation:delivered')
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)

    def qualify(self,**changes):
        return review.qualify(self.cfg,changes.get('state',self.s),changes.get('author',self.author),
            changes.get('binding',self.binding),changes.get('snapshot',self.s['snapshot']))

    def test_red_gate_qualifies_review_only_without_claiming_failure_of_passing_ordering(self):
        facts=self.qualify();self.assertTrue(facts['stale_ordering_passed']);self.assertFalse(facts['poll_requests_passed'])
        self.assertFalse(facts['delivery_approval'])
        for changed in (dict(revision=1),dict(history=[{}]),dict(failed_inspection_review='already-used'),
                dict(category='some-other-failure'),dict(source_reset=True)):
            with self.assertRaises(ValueError):self.qualify(state={**self.s,**changed})

    def test_wrong_actor_wakeup_live_binding_or_foreign_snapshot_cannot_enter_review(self):
        for changed in (dict(agent_id='lead'),dict(wakeup_id='other'),dict(status='running')):
            with self.assertRaises(ValueError):self.qualify(author={**self.author,**changed})
        with self.assertRaises(ValueError):self.qualify(binding={**self.binding,'status':'running'})
        with self.assertRaises(ValueError):self.qualify(snapshot={**self.s['snapshot'],'task_id':'foreign'})

    def journal(self):
        key,identity=review.inspection_identity(self.b,self.cfg,self.s)
        output=json.dumps(self.inspection,sort_keys=True)
        result=dict(container_id='captured',approval=False,exit_code=0,output=output,
            output_sha256=hashlib.sha256(output.encode()).hexdigest(),validation_job_key=key,
            validation_contract_sha256=review.job_digest(identity))
        self.s['inspection']={**self.inspection,'validation_job':result}
        self.con.execute('CREATE TABLE validation_jobs(job_key,identity,state)')
        self.con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',(key,json.dumps(identity),
            json.dumps(dict(stage='complete',container_id='captured',deadline=0,result=result))))
        return result

    def test_complete_fixed_job_receipt_is_authenticated_without_reexecuting_even_after_deadline(self):
        result=self.journal()
        self.assertEqual(review.completed_inspection(self.con,self.b,self.cfg,self.s),result)
        self.s['inspection']['reports']['guarded']['poll_requests']=3
        with self.assertRaises(ValueError):review.completed_inspection(self.con,self.b,self.cfg,self.s)

    def test_register_is_idempotent_and_preserves_failed_snapshot_and_revision(self):
        self.journal();self.b.LOCK=threading.RLock();self.b.db=lambda:self.con
        self.b.docker=lambda method,path:dict(Labels={'delivery-kit.owner':self.b.OWNER,'delivery-kit.source-task':'delivered'})
        self.con.executescript('CREATE TABLE leases(request_id,status);'
            'CREATE TABLE native_bindings(task_id,agent_id,issue_id,scope,request_id);'
            'CREATE TABLE snapshots(task_id,volume,status);CREATE TABLE literal_maintenance_workflows(source_task,config,state);')
        self.con.execute('INSERT INTO leases VALUES(?,?)',('request','closed'))
        self.con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',('delivered','author','child',self.binding['scope'],'request'))
        self.con.execute('INSERT INTO snapshots VALUES(?,?,?)',('delivered','frozen-delivered','complete'))
        self.con.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',('original',json.dumps(self.cfg),json.dumps(self.s)));self.con.commit()
        fx=Mock();fx.plans.task.return_value=self.author
        with patch.object(review.maintenance,'current',return_value=dict(stage='sealed',operation_id='window')),\
                patch.object(review.maintenance,'native_active',return_value=[]),patch.object(review.lane,'Effects',return_value=fx),\
                patch.object(review.flow,'authenticate'):
            receipt=review.register(self.b,'original');self.assertEqual(review.register(self.b,'original'),receipt)
        fx.plans.task.assert_called_once()
        current=json.loads(self.con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()[0])
        self.assertEqual(current['stage'],'review_dispatch');self.assertEqual(current['revision'],0)
        self.assertEqual(current['snapshot'],self.s['snapshot']);self.assertEqual(receipt['previous_state'],self.s)
        self.assertFalse(receipt['author_retry_authorized']);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(self.con.execute('SELECT count(*) FROM literal_failed_inspection_reviews').fetchone()[0],1)
        compile(cli.PROGRAM,'operator-review-program','exec')
