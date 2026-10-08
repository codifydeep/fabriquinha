import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import test_product_scope_revision as fixtures
from broker import product_scope_ledger as ledger
from broker import product_scope_execution as execution


class ProductScopeMountTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ProductScopeRevisionTests();f.setUp()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name)/'state.sqlite'
        @contextmanager
        def db():
            con=sqlite3.connect(path);con.row_factory=sqlite3.Row
            try:
                with con:yield con
            finally:con.close()
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock(),OWNER='owner')
        self.fx=Mock()
        self.fx.verify_binding.return_value=None
        self.fx.wake.return_value={'id':'wake'}
        self.b.docker=Mock(return_value={'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'source'}})
        with db() as con:
            self.key=ledger.open_plan(con,f.original,f.context)['key']
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT)')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('request','task','issue','cto'))
            con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute('INSERT INTO snapshots VALUES (?,?,?)',('source','snapshot','complete'))
            state=ledger.load(con,self.key)
            marker,note=execution.dispatch_note(state,'proposal')
            ledger.save_transition(con,state,dict(state,dispatch={'proposal':{'stage':'intent','marker':marker}}))
        self.task=dict(id='task',agent_id='cto',issue_id='issue',wakeup_id='wake',status='running',
                       handoff_note='DELIVERY_PLANNING_START '+marker+'\nSource: source\n'+note)
        self.fx.task.return_value=self.task

    def test_pending_ack_mount_is_exact_owned_snapshot_and_always_read_only(self):
        result=execution.mounts(self.b,'request',self.fx)
        self.assertEqual(result,[{'Type':'volume','Source':'snapshot','Target':'/evidence/candidate','ReadOnly':True}])
        self.assertFalse(self.fx.wake.call_args.kwargs['allow_create'])
        self.assertEqual(self.fx.task.call_args.args,('task','cto'))
        self.assertEqual(execution.mounts(self.b,'request',self.fx),result)

    def test_unrelated_request_has_no_scope_mount_and_does_not_fetch_native_state(self):
        self.assertEqual(execution.mounts(self.b,'unrelated',self.fx),[])
        self.fx.task.assert_not_called();self.fx.wake.assert_not_called()

    def test_wrong_native_task_wakeup_or_instruction_cannot_obtain_snapshot(self):
        for mutation in ({'id':'other'},{'agent_id':'lead'},{'issue_id':'another'},
                         {'wakeup_id':'another'},{'handoff_note':'DELIVERY_PRODUCT_SCOPE_V1:invented'},{'status':'completed'}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.fx.task.return_value={**self.task,**mutation}
                execution.mounts(self.b,'request',self.fx)

    def test_older_technical_task_does_not_inherit_new_scope_snapshot(self):
        self.fx.task.return_value={**self.task,'handoff_note':'DELIVERY_STRUCTURED_DECISION_V1:technical'}
        self.assertEqual(execution.mounts(self.b,'request',self.fx),[])
        self.fx.wake.assert_not_called();self.b.docker.assert_not_called()

    def test_replaced_volume_or_closed_plan_never_falls_back_to_old_diagnosis(self):
        self.b.docker.return_value={'Labels':{'delivery-kit.owner':'other','delivery-kit.source-task':'source'}}
        with self.assertRaises(ValueError):execution.mounts(self.b,'request',self.fx)
        self.b.docker.return_value={'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'source'}}
        with self.b.db() as con:
            state=ledger.load(con,self.key)
            ledger.save_transition(con,state,dict(state,stage='plan_approved'))
        with self.assertRaises(ValueError):execution.mounts(self.b,'request',self.fx)

    def test_legacy_installation_without_scope_plans_is_unchanged(self):
        with self.b.db() as con:con.execute('DROP TABLE product_scope_plans')
        self.assertEqual(execution.mounts(self.b,'request',self.fx),[])
        self.fx.task.assert_not_called()
