import copy
import unittest
from unittest.mock import patch
import integrate_u3_coverage as gate


class CoverageIntegrationTests(unittest.TestCase):
    def fixture(self):
        bundle=dict(source_task='source',contract=dict(manifest_sha256='a'*64,author='author'),receipt={'prior':'receipt'})
        final=dict(schema='u3-final-coverage-review-v1',head_sha=gate.review.HEAD,base_sha=gate.review.BASE,
            pr_url=gate.review.PR,manifest_sha256='a'*64,source_task='source',review_task='task',
            reviewer=gate.review.REVIEWER,delivery_approval=True,historical_tdd_red=False,
            product_admission_authorized=False,merge_authorized=False,deploy_authorized=False,
            suite_sha256='b'*64,reads_sha256='c'*64)
        pub=dict(stage='pr_open',pr_number=36,head_sha=gate.review.HEAD,base_sha=gate.review.BASE,
            manifest_sha256='a'*64,review_receipt_sha256=gate.publication.digest(bundle['receipt']))
        return pub,bundle,final

    def test_only_exact_independently_approved_delivery_can_reach_merge_gate(self):
        pub,bundle,final=self.fixture()
        with patch.object(gate.publication,'validate_bundle'):
            gate.qualify(pub,bundle,final)
            for changed in (dict(head_sha='d'*40),dict(manifest_sha256='d'*64),
                    dict(reviewer='author'),dict(delivery_approval=False),dict(product_admission_authorized=True)):
                with self.assertRaises(ValueError):gate.qualify(pub,bundle,dict(final,**changed))
            with self.assertRaises(ValueError):gate.qualify(dict(pub,review_receipt_sha256='e'*64),bundle,final)

    def test_same_repository_fixed_head_branch_and_base_only(self):
        pub,_,_=self.fixture();repo=dict(full_name=gate.publication.REPOSITORY)
        pr=dict(number=36,head=dict(sha=gate.review.HEAD,ref=gate.publication.BRANCH,repo=repo),
            base=dict(sha=gate.review.BASE,ref='main',repo=repo),merged=False)
        gate.verify_pr(pr,pub)
        for side,changed in (('head',dict(sha='d'*40)),('base',dict(sha='d'*40)),
                             ('head',dict(repo=dict(full_name='fork/repo')))):
            bad=copy.deepcopy(pr);bad[side].update(changed)
            with self.assertRaises(ValueError):gate.verify_pr(bad,pub)
        merged=dict(pr,merged=True,merge_commit_sha='e'*40,base=dict(pr['base'],sha='e'*40))
        gate.verify_pr(merged,pub)

    def test_recovery_requires_exact_saved_merge_intent_not_new_approval_or_protection(self):
        pub,bundle,final=self.fixture()
        intent=gate.intent(pub,final,{'strict':'protection'},{'ci':'passed'})
        gate.verify_intent(intent,pub,final,{'strict':'protection'})
        for changed in (dict(head_sha='d'*40),dict(final_review_sha256='d'*64),
                        dict(protection_sha256='d'*64)):
            with self.assertRaises(ValueError):gate.verify_intent(dict(intent,**changed),pub,final,{'strict':'protection'})

    def test_uncertain_remote_merge_is_never_blindly_dispatched_again(self):
        self.assertTrue(gate.may_dispatch(None))
        self.assertTrue(gate.may_dispatch({'stage':'merge_intent'}))
        for stage in ('merge_dispatched','merge_observation_pending','waiting_main_ci','coverage_integrated'):
            self.assertFalse(gate.may_dispatch({'stage':stage}))
