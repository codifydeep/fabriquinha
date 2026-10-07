import copy
import json
import unittest
from unittest.mock import patch
import test_remediation_red_reference as fixtures
from broker import remediation_delivery as delivery


class RemediationDeliveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.RemediationRedReferenceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f=f; self.b=f.b; self.reference=f.register(); f.task()
        self.expected=dict(source_task='product-task',review_task='product-review',author='author',
            reviewer='product-reviewer',manifest_sha256='9'*64,volume='product-snapshot')
        red=self.reference['red']
        self.tdd=dict(mode='controller_test_first',red=red['red'],
            green=dict(manifest_sha256='9'*64,tests=323,executed_by_controller=True),
            test_task=red['task_id'],implementation_task='product-task',
            red_origin_issue=red['issue_id'],red_origin_scope=red['scope'])
        with self.b.db() as con:
            con.execute('CREATE TABLE delivery_tdd(task_id TEXT,receipt TEXT)')
            con.execute('INSERT INTO delivery_tdd VALUES (?,?)',('product-task',json.dumps(self.tdd)))
            con.execute('INSERT INTO delivery_handoffs (issue_id,source_task,stage,updated) VALUES (?,?,?,?)',('r2','product-task','approved',1))
            con.execute('CREATE TABLE snapshots(task_id TEXT PRIMARY KEY,volume TEXT,status TEXT)')
            con.execute('INSERT INTO snapshots VALUES (?,?,?)',('product-task','product-snapshot','complete'))
            con.execute('CREATE TABLE reviews(review_task_id TEXT,source_task_id TEXT,manifest_sha256 TEXT,status TEXT,reviewer_agent_id TEXT)')
            con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',('product-review','product-task','9'*64,'approved','product-reviewer'))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('product-review','r2','review-scope','product-reviewer','review-request'))
            con.execute('INSERT INTO grants VALUES (?,?)',('review-request','review'))
            con.execute('INSERT INTO leases VALUES (?,?)',('review-request','closed'))

    def invoke(self, expected=None):
        with patch.object(delivery.references,'qualified',return_value=self.reference),\
             patch.object(delivery.references,'task_red',return_value=self.reference['red']):
            return delivery.qualified(self.b,'r2',self.expected if expected is None else expected)

    def test_exports_exact_delivery_without_homologation_or_red_relabel(self):
        result=self.invoke()
        self.assertEqual(result['delivery'],self.expected)
        self.assertEqual(result['red_origin_issue'],'r1')
        self.assertEqual(result['red_origin_task'],self.reference['red']['task_id'])
        self.assertEqual(result['original_depth'],2)
        self.assertFalse(result['release_homologated'])
        self.assertEqual(self.invoke(),result)

    def test_stale_or_self_review_is_rejected(self):
        for change in (dict(review_task='stale'),dict(reviewer='author'),dict(manifest_sha256='0'*64),
                       dict(volume='other'),dict(author='other'),dict(source_task='old')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.invoke({**self.expected,**change})

    def test_new_pending_handoff_prevents_export_of_old_approval(self):
        with self.b.db() as con:
            con.execute('INSERT INTO delivery_handoffs (issue_id,source_task,stage,updated) VALUES (?,?,?,?)',('r2','new-task','review_pending',2))
        with self.assertRaises(ValueError):self.invoke()

    def test_tdd_origin_full_green_and_manifest_are_mandatory(self):
        for change in (dict(red_origin_issue='r2'),dict(test_task='product-task'),dict(red_origin_scope='review-scope'),
                       dict(implementation_task='other'),dict(mode='agent_declared'),
                       dict(green=dict(manifest_sha256='0'*64,tests=323,executed_by_controller=True)),
                       dict(green=dict(manifest_sha256='9'*64,tests=0,executed_by_controller=True)),
                       dict(green=dict(manifest_sha256='9'*64,tests=323,executed_by_controller=False)),
                       dict(red={**self.tdd['red'],'test_sha256':{}})):
            with self.b.db() as con:
                con.execute('UPDATE delivery_tdd SET receipt=?',(json.dumps({**self.tdd,**change}),))
            with self.subTest(change=change),self.assertRaises(ValueError):self.invoke()

    def test_open_review_lease_wrong_mode_and_revoked_verdict_rejected(self):
        for sql in ("UPDATE leases SET status='running' WHERE request_id='review-request'",
                    "UPDATE grants SET mode='implementation' WHERE request_id='review-request'",
                    "UPDATE reviews SET status='changes_requested'"):
            with self.b.db() as con:con.execute(sql)
            with self.assertRaises(ValueError):self.invoke()
            with self.b.db() as con:
                con.execute("UPDATE leases SET status='closed'")
                con.execute("UPDATE grants SET mode='review' WHERE request_id='review-request'")
                con.execute("UPDATE reviews SET status='approved'")

    def test_paused_route_and_missing_reference_never_admit_delivery(self):
        with patch.object(delivery.references,'qualified',return_value=None):
            with self.assertRaises(ValueError):delivery.qualified(self.b,'r2',self.expected)
        with self.b.db() as con:
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(self.f.route),'r2'))
        with self.assertRaises(ValueError):self.invoke()

    def test_incomplete_snapshot_and_missing_tdd_block_export(self):
        with self.b.db() as con:con.execute("UPDATE snapshots SET status='creating'")
        with self.assertRaises(ValueError):self.invoke()
        with self.b.db() as con:
            con.execute("UPDATE snapshots SET status='complete'")
            con.execute('DELETE FROM delivery_tdd')
        with self.assertRaises(ValueError):self.invoke()

    def test_rejects_boolean_or_partial_test_counts(self):
        for count in (True,1,'323'):
            bad=copy.deepcopy(self.tdd);bad['green']['tests']=count
            with self.b.db() as con:con.execute('UPDATE delivery_tdd SET receipt=?',(json.dumps(bad),))
            with self.assertRaises(ValueError):self.invoke()
