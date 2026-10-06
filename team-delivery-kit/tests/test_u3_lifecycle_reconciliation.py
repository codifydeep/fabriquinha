import copy
import json
import sqlite3
import unittest
from broker import u3_lifecycle_reconciliation as lifecycle
from broker.qa_cleanup_observer import digest


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE incremental_checkpoints(source_task TEXT PRIMARY KEY,state TEXT)')
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
        self.con.execute('CREATE TABLE leases(status TEXT)')
        self.before=dict(execution_authorized=True,delivery_approval=False,stage='awaiting_runtime_binding',
            units=dict(U1={'stage':'checkpointed'},U2={'stage':'checkpointed'},
                       U3=dict(stage='awaiting_red',revision=5,binding={'issue_id':'original'},history=[{'failed':True}]),
                       U4={'stage':'waiting_dependency'}))
        self.route=dict(enabled=True,issue_id='original',test_first=True)
        self.con.execute('INSERT INTO incremental_checkpoints VALUES(?,?)',('root',json.dumps(self.before)))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('original',json.dumps(self.route)))
        self.contract={'root':'root','work_issue_id':'maintenance','proposal_sha256':'a'*64,'review_task':'review'}

    def test_pause_preserves_every_original_field_and_does_not_release_dependents(self):
        receipt=lifecycle.reconcile(self.con,self.contract)
        current=json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])
        self.assertFalse(current['execution_authorized']);self.assertFalse(current['delivery_approval'])
        self.assertEqual(current['units']['U4'],self.before['units']['U4'])
        self.assertEqual(receipt['original_state'],self.before)
        self.assertEqual(receipt['original_route'],self.route)
        self.assertEqual(receipt['original_state_sha256'],digest(self.before))
        self.assertEqual(current['units']['U3']['binding'],self.before['units']['U3']['binding'])
        self.assertEqual(receipt,lifecycle.reconcile(self.con,self.contract))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM u3_lifecycle_reconciliations').fetchone()[0],1)

    def test_busy_controller_never_changes_any_state(self):
        self.con.execute('INSERT INTO leases VALUES(?)',('running',))
        with self.assertRaises(ValueError):lifecycle.reconcile(self.con,self.contract)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0]),self.before)

    def test_missing_or_wrong_original_binding_is_rejected(self):
        self.con.execute('DELETE FROM delivery_routes')
        with self.assertRaises(ValueError):lifecycle.reconcile(self.con,self.contract)

    def test_reentry_rejects_modified_receipt_contract_or_resumed_state(self):
        lifecycle.reconcile(self.con,self.contract)
        with self.assertRaises(ValueError):lifecycle.reconcile(self.con,dict(self.contract,review_task='other'))
        changed=copy.deepcopy(self.before)
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(changed),))
        with self.assertRaises(ValueError):lifecycle.reconcile(self.con,self.contract)

    def test_unexpected_revision_or_delivery_approval_is_not_reconciled(self):
        for key,value in [('delivery_approval',True),('execution_authorized',False)]:
            altered=dict(self.before,**{key:value})
            self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(altered),))
            with self.assertRaises(ValueError):lifecycle.reconcile(self.con,self.contract)

    def test_failed_route_write_rolls_back_receipt_and_root_together(self):
        self.con.execute("CREATE TRIGGER reject_route BEFORE UPDATE ON delivery_routes BEGIN SELECT RAISE(ABORT,'injected write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):lifecycle.reconcile(self.con,self.contract)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0]),self.before)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM u3_lifecycle_reconciliations').fetchone()[0],0)

    def test_already_disabled_route_is_preserved_and_cannot_be_reenabled_silently(self):
        self.route['enabled']=False
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(self.route),))
        receipt=lifecycle.reconcile(self.con,self.contract)
        self.assertEqual(receipt['original_route'],self.route)
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(dict(self.route,enabled=True)),))
        with self.assertRaises(ValueError):lifecycle.reconcile(self.con,self.contract)
