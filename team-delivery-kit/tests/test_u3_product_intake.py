import copy,unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from threading import RLock
from broker import u3_product_intake as intake

class ProductIntakeTests(unittest.TestCase):
    def fixture(self):
        c=dict(author='author',reviewer='reviewer',cto='cto',plan_config=dict(root='root'))
        history=[]
        for i in (1,2):
            digest=str(i)*64
            history.append(dict(criterion='C0'+str(i),author='author',reviewer='reviewer',review_task='review'+str(i),
                decision=dict(action='approve_test_revision',optional_files=[],manifest_sha256=digest),
                seed=dict(manifest_sha256=digest),validation=dict(manifest_sha256=digest,original_files_unchanged=True,
                    delivery_approval=False,full_suite=dict(tests=259+i,exit_code=0))))
        s=dict(stage='controls_review_approved',delivery_approval=False,history=history)
        baseline=dict(tests=255,successful=True,failures=[],errors=[],skipped=0);covered=dict(baseline,tests=261)
        proof=dict(schema='u3-product-coverage-probe-v1',classification='existing_behavior_coverage_only',
            controls_manifest_sha256='2'*64,previous_files_unchanged=True,new_code_required=False,
            historical_tdd_red=False,product_admission_authorized=False,delivery_approval=False,
            network='none',inputs_mount='readonly',model_calls=0,
            new_test_sha256={p:'a'*64 for p in ('tests/test_incremental_u3.py',*intake.controls.FILES.values())},
            baseline=baseline,original_with_approved_tests=covered,candidate=covered)
        return c,s,proof

    def test_qualification_is_not_historical_red_or_release_authority(self):
        c,s,p=self.fixture();certificate=intake.qualify(c,s,p)
        self.assertFalse(certificate['historical_tdd_red']);self.assertFalse(certificate['product_admission_authorized'])
        self.assertFalse(certificate['delivery_approval']);self.assertEqual(certificate['reviews'],['review1','review2'])

    def test_stale_review_modified_product_and_fake_red_are_rejected(self):
        c,s,p=self.fixture()
        for key,value in (('historical_tdd_red',True),('previous_files_unchanged',False),
                          ('controls_manifest_sha256','3'*64),('product_admission_authorized',True)):
            with self.assertRaises(ValueError):intake.qualify(c,s,dict(p,**{key:value}))
        changed=copy.deepcopy(s);changed['history'][0]['reviewer']='author'
        with self.assertRaises(ValueError):intake.qualify(c,changed,p)

    def test_unregistered_intake_has_no_mounts_or_dispatch(self):
        with patch.object(intake,'saved',return_value=None):
            self.assertEqual(intake.mounts(None,{}),[]);self.assertIsNone(intake.tick(None))

    def test_budget_gate_never_dispatches_with_45_calls_or_changes_reserve(self):
        import contextlib,json,tempfile
        from pathlib import Path
        c,current,proof=self.fixture()
        config=dict(proof=proof,certificate=intake.qualify(c,current,proof),cto='cto')
        state=dict(stage='awaiting_budget',minimum_calls=48)
        @contextlib.contextmanager
        def db():yield object()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}')
            b=SimpleNamespace(LOCK=RLock(),STATE=root,db=db);fx=Mock();fx.remaining_calls.return_value=45
            with patch.object(intake,'saved',return_value=(config,state)),\
                    patch.object(intake.controls,'saved',return_value=(c,current)),\
                    patch.object(intake.intake,'verify'),patch.object(intake.handoff_runtime,'Effects',return_value=fx):
                intake.tick(b);intake.tick(b)
                fx.remaining_calls.side_effect=intake.handoff_runtime.BudgetStatusUnavailable()
                intake.tick(b)
            fx.ensure_planning_start.assert_not_called();self.assertEqual(state['stage'],'awaiting_budget')
            self.assertEqual(state['minimum_calls'],48)
