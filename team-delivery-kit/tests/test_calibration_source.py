import copy
import json
import unittest
import contextlib
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch,Mock
from broker import calibration_source as source
from broker import literal_maintenance_workflow as flow,literal_maintenance_effects as effects,remediation_runtime_guard as guard


class CalibrationSourceTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(author='author',cto='cto',reviewer='lead',workflow_key='key',test_path='tests/new.py',source={'author_task':'original'})
        d=dict(agent_id='cto',task_id='review',value=dict(action='approve_test_revision',manifest_sha256='a'*64))
        self.s=dict(stage='maintenance_approved',review_phase='escalated',review=d,escalated_review=d,
            functional_red=False,delivery_approval=False,source_reset=False,issue_id='child',author_task='author-task',
            review_wakeup='wake',review_marker='mark',escalated_review_validation={'verified':True},
            inspection=dict(candidate_manifest_sha256='a'*64,stale_witness_selectivity_passed=True,
                structure=dict(candidate_test_sha256='b'*64)))
        self.fx=SimpleNamespace(verify=Mock(),plans=SimpleNamespace(task=Mock(return_value={})),
            decision=Mock(return_value=d),validate_escalated_review=Mock(return_value={'verified':True}),
            validate_inspection=Mock(),preserved_submission=Mock())
        self.addCleanup(patch.stopall)
        patch.object(effects,'Effects',return_value=self.fx).start()
        self.auths=[patch.object(flow,n).start() for n in ('authenticate','authenticate_escalated_review')]
    def test_native_maintenance_proof_is_calibration_only(self):
        p=source.authenticate(object(),self.cfg,self.s)
        self.assertEqual(p['manifest_sha256'],'a'*64)
        for k in ('source_reset','author_retry_authorized','execution_authorized','delivery_approval'):self.assertFalse(p[k])
        self.fx.preserved_submission.assert_called_once()
        for auth in self.auths:auth.assert_called_once()
    def test_approved_label_alone_or_stale_manifest_cannot_authorize(self):
        for key,value in (('stage','blocked'),('review_phase','review'),('functional_red',True),('delivery_approval',True)):
            s=copy.deepcopy(self.s);s[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):source.authenticate(object(),self.cfg,s)
        s=copy.deepcopy(self.s);s['review']['value']['manifest_sha256']='c'*64
        with self.assertRaises(ValueError):source.authenticate(object(),self.cfg,s)
    def test_native_receipt_mismatch_and_missing_read_proof_fail_closed(self):
        self.fx.decision.return_value={}
        with self.assertRaises(ValueError):source.authenticate(object(),self.cfg,self.s)
        self.fx.decision.return_value=self.s['review'];self.fx.validate_escalated_review.return_value={}
        with self.assertRaises(ValueError):source.authenticate(object(),self.cfg,self.s)
    def test_ordinary_calibration_uses_existing_runtime_guard_unchanged(self):
        with patch.object(guard,'qualified',return_value={'original':'contract'}) as original,patch.object(source,'lookup') as lookup:
            self.assertEqual(source.qualified(object(),'ordinary'),{'original':'contract'})
            original.assert_called_once();lookup.assert_not_called()
    def test_maintained_path_never_changes_the_product_runtime_guard(self):
        with patch.object(guard,'qualified',return_value=None),patch.object(source,'lookup',return_value=None):
            self.assertIsNone(source.qualified(object(),'unrelated'))

    def test_maintained_input_preserves_original_plan_and_requires_disabled_child_route(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        parent=dict(issue_id='original',author='author',cto='cto',techlead='lead',enabled=True)
        child=effects.maintenance_route(parent,'child')
        for issue,route in (('original',parent),('child',child)):
            con.execute('INSERT INTO delivery_routes VALUES(?,?)',(issue,json.dumps(route)))
        value=dict(plan_sha256='plan',amendment={'kind':'inherited_frozen_suite'},criteria={'A01':'original acceptance'})
        cfg=dict(self.cfg,route_sha256=flow.digest(parent),source=dict(issue_id='original',
            execution_sha256=flow.digest(value),plan_sha256='plan',criteria=value['criteria']))
        @contextlib.contextmanager
        def db():yield con
        b=SimpleNamespace(db=db)
        with patch.object(guard,'qualified',side_effect=lambda b,issue:value if issue=='original' else None),\
                patch.object(source,'lookup',return_value=(cfg,self.s)),patch.object(source,'authenticate'):
            self.assertEqual(source.qualified(b,'child'),value)
            child['enabled']=True;con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(child),'child'))
            with self.assertRaises(ValueError):source.qualified(b,'child')
            child['enabled']=False;con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(child),'child'))
            value['criteria']={'A01':'changed acceptance'}
            with self.assertRaises(ValueError):source.qualified(b,'child')
