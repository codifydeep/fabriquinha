import copy
import hashlib
import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager,ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import test_generic_calibration_proposal as samples
from broker import generic_calibration_proposal as proposal
from generic_harness_calibration import digest


class ProposalCollectorTests(unittest.TestCase):
    def setUp(self):
        fixture=samples.ProposalTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.value=copy.deepcopy(fixture.value)
        self.value['amendment']={'kind':'inherited_frozen_suite'}
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.executescript('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);'
            'CREATE TABLE test_first_jobs(job_key TEXT,identity TEXT,state TEXT);'
            'CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT);'
            'CREATE TABLE leases(request_id TEXT,status TEXT);')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(fixture.route)))
        for actor,mode in (('cto','planning'),('author','implementation')):
            self.con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                (actor,actor+'-task',actor,'workspace:'+actor+':'+mode+':'+actor+'-task','issue'))
            self.con.execute('INSERT INTO leases VALUES(?,?)',(actor,'closed'))
        payload=dict(Labels={'delivery-kit.test-first-task':'author-task'},
            HostConfig=dict(Mounts=[dict(Target='/snapshot',Source='delivery-kit-port2-candidate')]))
        raw=json.dumps(fixture.prepared)
        self.con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',('author-task:copy',json.dumps({'payload':payload}),
            json.dumps(dict(stage='complete',result=dict(output=raw,exit_code=0,approval=False,
                output_sha256=hashlib.sha256(raw.encode()).hexdigest())))))
        @contextmanager
        def db():
            yield self.con
            self.con.commit()
        self.effects=[]
        def docker(method,path,body=None):
            self.effects.append((method,path))
            self.assertEqual(method,'GET')
            return dict(Labels={'delivery-kit.owner':'owned','delivery-kit.test-first-task':'author-task'})
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=db,docker=docker,OWNER='owned',PREFIX='delivery-kit-port2')
        self.task=dict(id='cto-task',agent_id='cto',issue_id='issue',wakeup_id='wake',status='completed',
            result=dict(output=json.dumps(fixture.body)))
        reads={path:dict(lines=3,total_lines=3) for path in proposal.source_paths(fixture.body)}
        self.fx=SimpleNamespace(settings={'agents':{'cto':'planning','author':'implementation'}},
            task=lambda tid,actor:self.task if actor=='cto' else dict(status='completed',issue_id='issue'),
            reads=lambda t:reads)

    def collect(self):
        from broker import remediation_runtime_guard as guard,remediation_admission as admission,technical_remediation_plan as plans
        with ExitStack() as stack:
            stack.enter_context(patch.object(guard,'qualified',return_value=self.value))
            stack.enter_context(patch.object(admission,'Effects',return_value=SimpleNamespace(plan=lambda source:(
                dict(cto='cto',reviewer='lead',original_author='author'),dict(plan_sha256=self.value['plan_sha256'])))))
            stack.enter_context(patch.object(plans,'Effects',return_value=self.fx))
            return proposal.collect(self.b,'issue','author-task','cto-task','wake')

    def test_collector_reads_native_output_and_closed_bindings_without_any_mutation(self):
        record=self.collect()
        self.assertEqual(record['producer']['actor'],'cto')
        self.assertEqual(record['candidate_volume'],'delivery-kit-port2-candidate')
        self.assertEqual(record['policy']['execution_sha256'],digest(self.value))
        self.assertFalse(record['execution_authorized'])
        self.assertTrue(self.effects)
        self.assertTrue(all(method=='GET' for method,path in self.effects))
        self.assertEqual(self.collect(),record)

    def test_nonclosed_or_wrong_role_lease_cannot_supply_proposal(self):
        self.con.execute('UPDATE leases SET status=? WHERE request_id=?',('running','cto'))
        with self.assertRaises(ValueError):self.collect()
        self.assertFalse(self.effects)
        self.con.execute('UPDATE leases SET status=? WHERE request_id=?',('closed','cto'))
        self.con.execute('UPDATE native_bindings SET agent_id=? WHERE request_id=?',('author','cto'))
        with self.assertRaises(ValueError):self.collect()

    def test_stale_native_wakeup_and_corrupted_copy_receipt_cannot_be_registered(self):
        self.task['wakeup_id']='foreign'
        with self.assertRaises(ValueError):self.collect()
        self.task['wakeup_id']='wake'
        raw=self.con.execute('SELECT state FROM test_first_jobs').fetchone()[0]
        state=json.loads(raw);state['result']['output_sha256']='0'*64
        self.con.execute('UPDATE test_first_jobs SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):self.collect()
