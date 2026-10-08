import json
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from broker import review_suite_rpc as rpc


class RpcTests(unittest.TestCase):
    def test_pending_job_is_observed_not_failed_or_approved(self):
        from broker.validation_job import Pending
        result=self.broker.validate_frozen_delivery.return_value
        self.broker.validate_frozen_delivery.side_effect=[Pending('same running handle'),result]
        token=rpc.issue(self.broker,'request')
        receipt=rpc.execute(self.broker,token,{})
        self.assertEqual(receipt['exit_code'],0)
        self.assertEqual(self.broker.validate_frozen_delivery.call_count,2)
        self.assertEqual(self.broker.validate_frozen_delivery.call_args_list[0],
                         self.broker.validate_frozen_delivery.call_args_list[1])
    def test_legacy_interrupted_capability_is_not_upgraded(self):
        token=rpc.issue(self.broker,'request')
        with self.db() as con:con.execute("UPDATE review_suite_rpc SET status='running'")
        with self.assertRaises(ValueError):rpc.execute(self.broker,token,{})
        self.broker.validate_frozen_delivery.assert_not_called()
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'db.sqlite'
        @contextmanager
        def db():
            con = sqlite3.connect(self.path);con.row_factory = sqlite3.Row
            try:
                with con: yield con
            finally: con.close()
        self.db = db
        with db() as con:
            for sql in (
                'CREATE TABLE grants(task_id,mode,deadline,used,attempt,request_id)',
                'CREATE TABLE native_bindings(request_id,task_id,agent_id,scope,issue_id)',
                'CREATE TABLE leases(request_id,status,deadline)',
                'CREATE TABLE review_bindings(request_id,source_task_id,volume)',
                'CREATE TABLE review_assignments(review_agent_id,source_task_id,volume)',
                'CREATE TABLE snapshots(task_id,volume,status)'):
                con.execute(sql)
            con.execute('INSERT INTO grants VALUES (?,?,?,?,?,?)',
                        ('review', 'review', time.time()+300, 1, 1, 'request'))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',
                        ('request', 'review', 'reviewer', 'scope', 'issue'))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',
                        ('author-request', 'source', 'author', 'source-scope', 'issue'))
            con.execute('INSERT INTO leases VALUES (?,?,?)', ('request','running',time.time()+300))
            con.execute('INSERT INTO review_bindings VALUES (?,?,?)', ('request','source','volume'))
            con.execute('INSERT INTO review_assignments VALUES (?,?,?)', ('reviewer','source','volume'))
            con.execute('INSERT INTO snapshots VALUES (?,?,?)', ('source','volume','complete'))
        validation = {'portable': True, 'manifest_sha256': 'a'*64, 'tests': 138,
                      'suite': {'output':'Ran 138 tests in 1s\nOK\n',
                                'test_image':'sha256:'+'b'*64,
                                'test_command':['python3','-m','unittest'],
                                'output_sha256':'c'*64}}
        self.broker = SimpleNamespace(LOCK=threading.RLock(),db=db,TOKEN='admin-secret',
            validate_frozen_delivery=Mock(return_value=validation), assert_review_task_running=Mock())

    def test_fixed_operation_is_durable_cached_and_bound_to_review_snapshot(self):
        token = rpc.issue(self.broker,'request')
        self.assertNotEqual(token,self.broker.TOKEN)
        receipt = rpc.execute(self.broker,token,{})
        self.assertEqual(receipt['executed_by'],'controller_offline_review_suite')
        self.assertEqual(receipt['review_task'],'review')
        self.assertEqual(receipt['manifest_sha256'],'a'*64)
        self.assertEqual(rpc.execute(self.broker,token,{}),receipt)
        self.broker.validate_frozen_delivery.assert_called_once_with('volume','source',suite_evidence=True,
                                                                   review_request_id='request')
        self.assertEqual(rpc.issue(self.broker,'request'),token)

    def test_agent_arguments_and_admin_token_cannot_select_or_execute_command(self):
        token = rpc.issue(self.broker,'request')
        for payload in ({'command':'id'}, {'image':'latest'}, {'source_task':'other'}):
            with self.assertRaises(ValueError): rpc.execute(self.broker,token,payload)
        for denied in ('x'*64, self.broker.TOKEN):
            with self.assertRaises(ValueError): rpc.execute(self.broker,denied,{})
        self.broker.validate_frozen_delivery.assert_not_called()

    def test_stale_closed_expired_and_self_review_never_execute(self):
        token = rpc.issue(self.broker,'request')
        for sql, undo in (
                ("UPDATE leases SET status='closed'", "UPDATE leases SET status='running'"),
                ("UPDATE leases SET deadline=0", 'UPDATE leases SET deadline=' + str(time.time()+300)),
                ("UPDATE grants SET mode='implementation'", "UPDATE grants SET mode='review'"),
                ("UPDATE review_assignments SET volume='other'", "UPDATE review_assignments SET volume='volume'"),
                ("UPDATE native_bindings SET agent_id='reviewer' WHERE task_id='source'",
                 "UPDATE native_bindings SET agent_id='author' WHERE task_id='source'")):
            with self.db() as con:
                con.execute(sql)
            with self.assertRaises(ValueError): rpc.execute(self.broker,token,{})
            with self.db() as con:
                con.execute(undo)
        self.broker.validate_frozen_delivery.assert_not_called()

    def test_failed_or_interrupted_call_is_not_replayed_automatically(self):
        token = rpc.issue(self.broker,'request')
        self.broker.validate_frozen_delivery.side_effect = TimeoutError('offline failure')
        with self.assertRaises(TimeoutError): rpc.execute(self.broker,token,{})
        with self.assertRaisesRegex(ValueError,'diagnosis required'): rpc.execute(self.broker,token,{})
        self.assertEqual(self.broker.validate_frozen_delivery.call_count,1)
        with self.db() as con: con.execute("UPDATE review_suite_rpc SET status='running'")
        with self.assertRaisesRegex(ValueError,'diagnosis required'): rpc.execute(self.broker,token,{})

    def test_native_cancellation_blocks_even_a_cached_success(self):
        token = rpc.issue(self.broker,'request')
        rpc.execute(self.broker,token,{})
        self.broker.assert_review_task_running.side_effect=ValueError('cancelled')
        with self.assertRaisesRegex(ValueError,'cancelled'): rpc.execute(self.broker,token,{})

    def test_text_only_or_stale_snapshot_cannot_approve_new_review(self):
        token = rpc.issue(self.broker,'request')
        with self.db() as con:
            with self.assertRaisesRegex(ValueError,'exact offline'):
                rpc.require_approval_proof(con,'request','source','a'*64)
        rpc.execute(self.broker,token,{})
        with self.db() as con:
            rpc.require_approval_proof(con,'request','source','a'*64)
            with self.assertRaisesRegex(ValueError,'exact offline'):
                rpc.require_approval_proof(con,'request','source','b'*64)
