"""Synthetic final-review facts, never a native reviewer or merge grant."""
import copy
import unittest
import quality_delivery_review_policy as policy
from broker import quality_lifecycle_v2 as q
import test_quality_lifecycle_v2 as fixtures


class QualityDeliveryReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityLifecycleTests();f.setUp();self.plan=f.p;self.evidence=f.proofs()
        self.validation=dict(operation='observed_delivery_review_validation_v2',run_id=f.p['run_id'],
            issue_id=f.p['issue_id'],contract_sha256=f.p['contract_sha256'],plan_sha256=q.digest(f.p),
            task_id='delivery-review-task',request_id='60000000-0000-4000-8000-000000000009',
            reviewer=f.p['reviewer'],quality_evidence_sha256=q.digest(self.evidence),
            manifest_sha256=f.g['manifest_sha256'],commit_sha=f.g['commit_sha'],
            job_receipt_sha256='8'*64,network='none',snapshot_mount='readonly',
            **{k:copy.deepcopy(f.g[k]) for k in q.suite_fields(f.p)})
        self.review=dict(operation='independent_delivery_review_v2',run_id=f.p['run_id'],issue_id=f.p['issue_id'],
            contract_sha256=f.p['contract_sha256'],plan_sha256=q.digest(f.p),task_id='delivery-review-task',
            author=f.p['author'],reviewer=f.p['reviewer'],manifest_sha256=f.g['manifest_sha256'],commit_sha=f.g['commit_sha'],
            red_sha256=q.digest(f.r),test_review_sha256=q.digest(f.review),green_sha256=q.digest(f.g),
            sensitivity_sha256=q.digest(f.m),validation_sha256=q.digest(self.validation),
            decision='approve_delivery',criteria=list(f.p['criteria']),complete_reads=True,read_only=True)

    def qualify(self):return policy.qualify(self.plan,self.evidence,self.review,self.validation)

    def test_exact_independent_facts_never_authorize_publication_or_release(self):
        before=copy.deepcopy((self.plan,self.evidence,self.review,self.validation))
        result=self.qualify();self.assertEqual(self.qualify(),result)
        self.assertEqual(result['commit_sha'],self.evidence['green']['commit_sha'])
        self.assertEqual(result['review_sha256'],q.digest(self.review))
        self.assertFalse(result['merge_authorized']);self.assertFalse(result['delivery_approval'])
        self.assertEqual(before,(self.plan,self.evidence,self.review,self.validation))

    def test_review_cannot_skip_red_test_review_green_or_negative_controls(self):
        for key in self.evidence:
            evidence=copy.deepcopy(self.evidence);del evidence[key]
            with self.subTest(key=key),self.assertRaises(ValueError):policy.qualify(self.plan,evidence,self.review,self.validation)
        self.evidence['sensitivity']['controls'][0]['criteria']=['A01']
        with self.assertRaises(ValueError):self.qualify()

    def test_exact_new_readonly_reviewer_and_all_criteria_are_required(self):
        for change in (dict(reviewer='author'),dict(author='another'),dict(task_id='tests-task'),
                dict(task_id='review-task'),dict(task_id='implementation-task'),dict(complete_reads=False),
                dict(complete_reads=1),dict(read_only=False),dict(criteria=['A01']),dict(decision='approve_tests'),
                dict(merge_authorized=True)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                policy.qualify(self.plan,self.evidence,{**self.review,**change},self.validation)

    def test_stale_sha_or_upstream_evidence_never_transfers_approval(self):
        for field in ('manifest_sha256','commit_sha','red_sha256','test_review_sha256',
                'green_sha256','sensitivity_sha256','validation_sha256','plan_sha256'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                policy.qualify(self.plan,self.evidence,{**self.review,field:'0'*len(self.review[field])},self.validation)

    def test_implementer_green_is_not_reviewer_owned_validation(self):
        with self.assertRaises(ValueError):policy.qualify(self.plan,self.evidence,self.review,self.evidence['green'])
        for change in (dict(task_id='implementation-task'),dict(reviewer='author'),dict(request_id='not-a-request'),
                dict(network='bridge'),dict(snapshot_mount='readwrite'),dict(quality_evidence_sha256='0'*64),
                dict(commit_sha='0'*40),dict(manifest_sha256='0'*64),dict(job_receipt_sha256='not-a-hash'),
                dict(delivery_approval=True)):
            value={**self.validation,**change};review={**self.review,'validation_sha256':q.digest(value)}
            with self.subTest(change=change),self.assertRaises(ValueError):policy.qualify(self.plan,self.evidence,review,value)

    def test_reviewer_suite_must_be_complete_and_keep_every_frozen_test(self):
        for change in (dict(tests_run=4),dict(tests_run=6),dict(tests_run=True),dict(skipped=1),dict(errors=1),
                dict(suite_complete=False),dict(exit_code=1),dict(tests={}),
                dict(tests={**self.validation['tests'],'tests/test_new.py':'0'*64})):
            value={**self.validation,**change};review={**self.review,'validation_sha256':q.digest(value)}
            with self.subTest(change=change),self.assertRaises(ValueError):policy.qualify(self.plan,self.evidence,review,value)


if __name__=='__main__':unittest.main()
