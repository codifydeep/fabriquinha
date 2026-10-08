import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_product_scope_revision as fixtures
from broker import product_scope_ledger as ledger
from broker import product_scope_execution as execution
from broker.product_scope_revision import digest


class ProductScopeExecutionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ProductScopeRevisionTests();f.setUp()
        self.original,self.context,self.proposal=f.original,f.context,f.proposal
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db.sqlite'
        @contextmanager
        def db():
            con=sqlite3.connect(self.path)
            try:
                with con:yield con
            finally:con.close()
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with db() as con:self.key=ledger.open_plan(con,self.original,self.context)['key']
        self.fx=Mock()
        self.fx.wake.return_value={'id':'wake1','last_task_id':None}
        self.fx.verify_binding.return_value=None

    def task(self,actor,identifier,wake,output,status='completed'):
        return dict(id=identifier,agent_id=actor,issue_id='issue',wakeup_id=wake,status=status,
                    result={'output':json.dumps(output)})

    def test_unknown_wakeup_ack_reconciles_same_marker_before_observing_task(self):
        self.fx.wake.side_effect=[TimeoutError(),{'id':'wake1','last_task_id':None}]
        with self.assertRaises(TimeoutError):execution.tick(self.b,self.key,self.fx)
        with self.b.db() as con:first=ledger.load(con,self.key)
        self.assertEqual(first['dispatch']['proposal']['stage'],'intent')
        resumed=execution.tick(self.b,self.key,self.fx)
        self.assertEqual(resumed['dispatch']['proposal']['wakeup_id'],'wake1')
        self.assertEqual(self.fx.wake.call_args_list[0],self.fx.wake.call_args_list[1])
        self.assertTrue(resumed['author_blocked'])

    def test_proposal_and_review_use_real_completed_tasks_and_exact_reads(self):
        execution.tick(self.b,self.key,self.fx)
        self.fx.wake.return_value={'id':'wake1','last_task_id':'cto-task'}
        self.fx.task.return_value=self.task('cto','cto-task','wake1',self.proposal)
        self.fx.read_hashes.return_value=self.context['eligible_code_sha256']
        proposed=execution.tick(self.b,self.key,self.fx)
        self.assertEqual(proposed['stage'],'awaiting_review')
        self.fx.wake.return_value={'id':'wake2','last_task_id':None}
        execution.tick(self.b,self.key,self.fx)
        review=dict(operation='review_product_scope_revision_v1',proposal_sha256=digest(self.proposal),
                    decision='approve',reason='Needed; tests and acceptance unchanged.')
        self.fx.wake.return_value={'id':'wake2','last_task_id':'lead-task'}
        self.fx.task.return_value=self.task('lead','lead-task','wake2',review)
        approved=execution.tick(self.b,self.key,self.fx)
        self.assertEqual(approved['stage'],'plan_approved')
        self.assertTrue(approved['author_blocked'])
        self.assertFalse(approved['qualification']['write_grant_issued'])
        calls=self.fx.wake.call_count
        self.assertEqual(execution.tick(self.b,self.key,self.fx),approved)
        self.assertEqual(self.fx.wake.call_count,calls)

    def test_failed_task_or_text_only_terminal_retains_visible_hold_without_retry(self):
        for status,output in (('failed',self.proposal),('completed','I changed the files')):
            with self.subTest(status=status):
                # Fresh isolated intent to avoid resetting an incident.
                context=dict(self.context,source_task='source-'+status)
                with self.b.db() as con:key=ledger.open_plan(con,self.original,context)['key']
                self.fx.wake.return_value={'id':'wake','last_task_id':'bad-task'}
                self.fx.task.return_value=self.task('cto','bad-task','wake',output,status)
                held=execution.tick(self.b,key,self.fx)
                self.assertEqual(held['stage'],'blocked')
                self.assertTrue(held['author_blocked'])
                count=self.fx.wake.call_count
                execution.tick(self.b,key,self.fx)
                self.assertEqual(self.fx.wake.call_count,count)

    def test_binding_drift_blocks_before_any_native_dispatch(self):
        self.fx.verify_binding.side_effect=ValueError('drift')
        with self.assertRaises(ValueError):execution.tick(self.b,self.key,self.fx)
        self.fx.wake.assert_not_called()

    def test_missing_proposal_reads_block_without_accepting_model_permission_request(self):
        self.fx.wake.return_value={'id':'wake','last_task_id':'task'}
        self.fx.task.return_value=self.task('cto','task','wake',self.proposal)
        self.fx.read_hashes.return_value={}
        held=execution.tick(self.b,self.key,self.fx)
        self.assertEqual(held['stage'],'blocked')
        self.assertNotIn('proposal',held)

    def test_native_binding_requires_current_failed_source_and_qualified_validator_inventory(self):
        self.b.OFFLINE_IMAGE='validator';self.b.OWNER='owner'
        self.b.docker=Mock(return_value={'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'source'}})
        failure=dict(category='executed_test_failure',source_task='source',volume='snapshot',
                     output_sha256=self.context['failure_output_sha256'],
                     diagnostic_source_hashes=self.context['eligible_code_sha256'])
        proof=dict(manifest_sha256=self.context['snapshot_sha256'],baseline_tests_intact=True,
                   new_test_sha256=self.context['frozen_test_sha256'],
                   diagnostic_file_sha256=self.context['eligible_code_sha256'])
        output=json.dumps(proof)
        identity=dict(task='source',kind='structure',payload={'Image':'validator','HostConfig':{
            'Mounts':[{'Source':'snapshot','ReadOnly':True}]}})
        job=dict(stage='complete',result={'exit_code':0,'output':output,
                                         'output_sha256':hashlib.sha256(output.encode()).hexdigest()})
        with self.b.db() as con:
            con.executescript('CREATE TABLE delivery_handoffs(source_task TEXT,stage TEXT,data TEXT,issue_id TEXT,updated REAL);'
                'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT);'
                'CREATE TABLE native_bindings(request_id TEXT,issue_id TEXT,agent_id TEXT);'
                'CREATE TABLE leases(request_id TEXT,status TEXT);CREATE TABLE validation_jobs(identity TEXT,state TEXT);')
            con.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?,?)',
                        ('source','technical_decision_required',json.dumps({'validation_failure':failure}),'issue',1))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(dict(
                contract_sha256=self.context['contract_sha256'],author='backend',cto='cto',techlead='lead',enabled=True))))
            con.execute('INSERT INTO snapshots VALUES (?,?,?)',('source','snapshot','complete'))
            con.execute('INSERT INTO validation_jobs VALUES (?,?)',(json.dumps(identity),json.dumps(job)))
            state=ledger.load(con,self.key)
        fx=execution.NativeEffects.__new__(execution.NativeEffects);fx.b=self.b;fx.settings={}
        with patch.object(execution.native,'task_record',return_value=dict(status='completed',issue_id='issue')):
            fx.verify_binding(state)
            with self.b.db() as con:
                corrupt=dict(job,result=dict(job['result'],output_sha256='0'*64))
                con.execute('UPDATE validation_jobs SET state=?',(json.dumps(corrupt),))
            with self.assertRaises(ValueError):fx.verify_binding(state)

    def test_read_hash_is_from_complete_observed_content_not_agent_claim(self):
        content='def get_item():\n    return None\n'
        sha=hashlib.sha256(content.encode()).hexdigest()
        path='/evidence/candidate/app/store.py'
        messages=[dict(type='tool_use',tool='read_file',call_id='read',input={'path':path}),
                  dict(type='tool_result',tool='read_file',call_id='read',output=json.dumps({
                      'content':'1|def get_item():\n2|    return None','total_lines':2}))]
        self.assertEqual(execution.observed_hashes(messages,{'app/store.py':sha}),{'app/store.py':sha})
        for expected in ({'app/store.py':'0'*64},{'app/db.py':sha}):
            with self.assertRaises(ValueError):execution.observed_hashes(messages,expected)
        messages[-1]['output']=json.dumps({'content':'1|def get_item():','total_lines':2})
        with self.assertRaises(ValueError):execution.observed_hashes(messages,{'app/store.py':sha})
