import copy
import contextlib
import json
from pathlib import Path
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from broker import u3_coverage_integration as integration


class CoverageIntegrationTests(unittest.TestCase):
    def fixture(self):
        manifest = 'a' * 64
        proof = dict(base_sha='b' * 40, base_manifest_sha256='c' * 64,
            previous_files_unchanged=True, historical_tdd_red=False,
            new_test_sha256={p: 'd' * 64 for p in (
                'tests/test_incremental_u3.py', *integration.controls.FILES.values())})
        config = dict(cto='cto', issue_id='classification', proof=proof,
            controls_config=dict(author='author', reviewer='reviewer'),
            certificate=dict(root='root', controls_manifest_sha256=manifest))
        decision = dict(action='approve_test_revision', manifest_sha256=manifest, optional_files=[])
        state = dict(stage='coverage_classification_approved', task_id='task', wakeup_id='wake',
            product_admission_authorized=False, delivery_approval=False, decision=decision)
        task = dict(id='task', agent_id='cto', issue_id='classification', wakeup_id='wake', status='completed')
        reads = {p: dict(lines=10, total_lines=10) for p in integration.intake.paths()}
        return config, state, task, decision, reads

    def test_completed_exact_classification_required(self):
        c, s, t, d, r = self.fixture()
        self.assertEqual(integration.approved(c, s, t, d, r), 'a' * 64)
        for key, value in (('agent_id','author'), ('issue_id','other'), ('wakeup_id','old'),
                           ('id','old'), ('status','failed')):
            with self.assertRaises(ValueError):
                integration.approved(c, s, dict(t, **{key:value}), d, r)

    def test_approval_never_upgrades_feature_or_release_authority(self):
        c, s, t, d, r = self.fixture()
        for key in ('delivery_approval', 'product_admission_authorized'):
            with self.assertRaises(ValueError):
                integration.approved(c, dict(s, **{key:True}), t, d, r)
        result = integration.contract(c, c['proof'], 'reviewer')
        for key in ('historical_tdd_red','product_admission_authorized','delivery_approval',
                    'merge_authorized','deploy_authorized'):
            self.assertIs(result[key], False)

    def test_partial_or_absent_read_rejected(self):
        c, s, t, d, r = self.fixture()
        for changed in ({}, dict(r, **{integration.intake.paths()[0]:dict(lines=1,total_lines=10)})):
            with self.assertRaises(ValueError):integration.approved(c,s,t,d,changed)

    def test_independence_and_proof_drift_rejected(self):
        c, _, _, _, _ = self.fixture()
        for reviewer in ('author','cto','other'):
            with self.assertRaises(ValueError):integration.contract(c,c['proof'],reviewer)
        p=copy.deepcopy(c['proof']);p['new_test_sha256']['app/static/app.js']='e'*64
        with self.assertRaises(ValueError):integration.contract(c,p,'reviewer')

    def test_independent_receipt_has_no_merge_deploy_or_historical_red(self):
        c,s,t,d,r=self.fixture()
        entry=dict(contract=integration.contract(c,c['proof'],'reviewer'),reviewer='reviewer',issue_id='review')
        task=dict(t,agent_id='reviewer',issue_id='review')
        receipt=integration.review_receipt(entry,s,task,d,r)
        self.assertTrue(receipt['integration_review_approved'])
        for key in ('delivery_approval','merge_authorized','deploy_authorized','historical_tdd_red'):
            self.assertFalse(receipt[key])
        self.assertEqual(receipt['manifest_sha256'],'a'*64)

    def test_stale_review_and_request_changes_do_not_authorize_integration(self):
        c,s,t,d,r=self.fixture()
        entry=dict(contract=integration.contract(c,c['proof'],'reviewer'),reviewer='reviewer',issue_id='review')
        task=dict(t,agent_id='reviewer',issue_id='review')
        for changed in (dict(d,manifest_sha256='e'*64),dict(d,action='reject_test_revision'),
                        dict(d,optional_files=['test.py'])):
            with self.assertRaises(ValueError):integration.review_receipt(entry,s,task,changed,r)

    def test_no_intake_means_no_side_effect(self):
        with patch.object(integration.intake,'saved',return_value=None),patch.object(integration,'prepare') as prepare:
            integration.tick(None);prepare.assert_not_called()
        with patch.object(integration,'saved',return_value=None):
            self.assertEqual(integration.mounts(None,{}),[])

    def test_budget_and_proxy_restart_preserve_pending_review(self):
        c,s,_,_,_=self.fixture()
        entry=dict(intake=c,classification_task='task',contract=integration.contract(c,c['proof'],'reviewer'),reviewer='reviewer')
        state=dict(stage='awaiting_budget',minimum_calls=32)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}');b=SimpleNamespace(LOCK=RLock(),STATE=root)
            fx=Mock();fx.remaining_calls.return_value=31
            with patch.object(integration.intake,'saved',return_value=(c,s)),\
                    patch.object(integration,'saved',return_value=(entry,state)),\
                    patch.object(integration,'verify',return_value=(c,s)),\
                    patch.object(integration.handoff_runtime,'Effects',return_value=fx),\
                    patch.object(integration,'save') as save:
                integration.tick(b)
                fx.remaining_calls.side_effect=integration.handoff_runtime.BudgetStatusUnavailable()
                integration.tick(b)
                fx.ensure_planning_start.assert_not_called();save.assert_not_called()
            self.assertEqual(state['stage'],'awaiting_budget')

    def test_terminal_gate_is_not_dispatched_again_after_restart(self):
        c,s,_,_,_=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}');b=SimpleNamespace(LOCK=RLock(),STATE=root)
            with patch.object(integration.intake,'saved',return_value=(c,s)),\
                    patch.object(integration.handoff_runtime,'Effects') as effects,\
                    patch.object(integration,'saved',return_value=({},dict(stage='integration_review_approved'))),\
                    patch.object(integration,'verify') as verify:
                integration.tick(b);integration.tick(b);verify.assert_not_called()
                effects.return_value.ensure_planning_start.assert_not_called()

    def test_preparation_failure_is_durable_and_not_repeated(self):
        import sqlite3
        c,s,_,_,_=self.fixture()
        con=sqlite3.connect(':memory:')
        @contextlib.contextmanager
        def db():
            yield con
            con.commit()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'native.json').write_text('{}')
                b=SimpleNamespace(LOCK=RLock(),STATE=root,db=db)
                with patch.object(integration.intake,'saved',return_value=(c,s)),\
                        patch.object(integration.handoff_runtime,'Effects'),\
                        patch.object(integration,'prepare',side_effect=ValueError('drift')) as prepare:
                    integration.tick(b);integration.tick(b)
                    prepare.assert_called_once()
                _,state=integration.saved(b)
                self.assertEqual(state['stage'],'blocked');self.assertEqual(state['owner'],'cto')
                self.assertFalse(state['delivery_approval'])
        finally:con.close()
