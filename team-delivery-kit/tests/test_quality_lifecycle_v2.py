"""Synthetic policy tests; never native execution or delivery qualification."""
import copy
import unittest
from broker import quality_lifecycle_v2 as q


class QualityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.p=dict(version=2,policy='red_review_green_sensitivity',run_id='new-run',issue_id='issue',
            contract_sha256='a'*64,base_sha='b'*40,author='author',reviewer='lead',
            criteria=['A01','A02'],baseline_tests={'tests/test_old.py':'c'*64},
            new_tests=['tests/test_new.py'],product_files=['app/app.js'],
            protected_files=['tests/test_old.py','tests/test_new.py','tests/harness.js','.github/workflows/ci.yml'],
            criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_new')],
                'A02':[dict(path='tests/test_new.py',method='test_other')]})
        self.r=dict(operation='observed_red_v2',run_id='new-run',issue_id='issue',
            contract_sha256='a'*64,task_id='tests-task',manifest_sha256='d'*64,
            tests={'tests/test_old.py':'c'*64,'tests/test_new.py':'e'*64},exit_code=1,
            suite_complete=True,tests_run=5,skipped=0,errors=0,
            failures=[dict(path='tests/test_new.py',method='test_new',phase='test_body',kind='assertion')])
        self.review=dict(operation='independent_test_review_v2',run_id='new-run',issue_id='issue',
            contract_sha256='a'*64,task_id='review-task',author='author',reviewer='lead',
            manifest_sha256='d'*64,red_sha256=q.digest(self.r),decision='approve_tests',
            criteria=['A01','A02'],complete_reads=True,read_only=True)
        self.g=dict(operation='observed_green_v2',run_id='new-run',issue_id='issue',
            contract_sha256='a'*64,task_id='implementation-task',manifest_sha256='f'*64,
            commit_sha='1'*40,red_sha256=q.digest(self.r),test_review_sha256=q.digest(self.review),
            tests=copy.deepcopy(self.r['tests']),exit_code=0,suite_complete=True,
            tests_run=5,skipped=0,errors=0,failures=[])
        self.m=dict(operation='observed_sensitivity_v2',run_id='new-run',issue_id='issue',
            contract_sha256='a'*64,green_sha256=q.digest(self.g),manifest_sha256='f'*64,
            commit_sha='1'*40,positive_sha256=q.digest(self.g),
            controls=[dict(id='missing-feature',criteria=['A01','A02'],
                changed_files=['app/app.js'],tests=copy.deepcopy(self.r['tests']),
                suite_complete=True,tests_run=5,skipped=0,errors=0,exit_code=1,
                failures=[dict(path='tests/test_new.py',method=m,phase='test_body',kind='assertion') for m in ('test_new','test_other')])])
        for receipt in (self.r,self.review,self.g,self.m):receipt['plan_sha256']=q.digest(self.p)
        self.review['red_sha256']=q.digest(self.r)
        self.g.update(red_sha256=q.digest(self.r),test_review_sha256=q.digest(self.review))
        self.m.update(green_sha256=q.digest(self.g),positive_sha256=q.digest(self.g))

    def proofs(self):return dict(red=self.r,test_review=self.review,green=self.g,sensitivity=self.m)

    def test_order_requires_no_positive_reference_before_real_red(self):
        self.assertEqual(q.next_stage(self.p,{}),'red')
        self.assertEqual(q.next_stage(self.p,dict(red=self.r)),'test_review')
        self.assertEqual(q.next_stage(self.p,dict(red=self.r,test_review=self.review)),'implementation')
        self.assertEqual(q.next_stage(self.p,dict(red=self.r,test_review=self.review,green=self.g)),'sensitivity')
        self.assertEqual(q.next_stage(self.p,self.proofs()),'independent_delivery_review')
        self.assertIs(q.qualify_sensitivity(self.p,self.proofs())['delivery_approval'],False)

    def test_green_or_sensitivity_cannot_skip_red_and_review(self):
        for evidence in (dict(green=self.g),dict(red=self.r,green=self.g),dict(sensitivity=self.m)):
            with self.subTest(evidence=evidence),self.assertRaises(ValueError):q.next_stage(self.p,evidence)

    def test_old_run_contract_or_manifest_is_not_reinterpreted(self):
        for field,value in (('run_id','old-run'),('contract_sha256','0'*64),('issue_id','old-issue')):
            evidence=self.proofs();evidence['red']={**self.r,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):q.next_stage(self.p,evidence)
        self.review['manifest_sha256']='0'*64
        with self.assertRaises(ValueError):q.next_stage(self.p,self.proofs())

    def test_red_requires_new_test_assertion_not_error_setup_skip_or_all_green(self):
        for change in (dict(exit_code=0),dict(errors=1),dict(skipped=1),dict(suite_complete=False),
                dict(failures=[]),dict(failures=[dict(path='tests/test_old.py',method='test_old',phase='test_body',kind='assertion')]),
                dict(failures=[dict(path='tests/test_new.py',method='test_new',phase='setUp',kind='assertion')]),
                dict(failures=[dict(path='tests/test_new.py',method='test_new',phase='test_body',kind='exception')])):
            with self.subTest(change=change),self.assertRaises(ValueError):q.next_stage(self.p,dict(red={**self.r,**change}))

    def test_review_is_independent_exact_read_only_and_covers_all_criteria(self):
        for change in (dict(reviewer='author'),dict(task_id='tests-task'),dict(complete_reads=False),
                dict(read_only=False),dict(criteria=['A01']),dict(decision='approve_delivery')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                q.next_stage(self.p,dict(red=self.r,test_review={**self.review,**change}))

    def test_green_cannot_weaken_tests_reduce_suite_or_use_stale_review(self):
        for change in (dict(tests={'tests/test_old.py':'c'*64,'tests/test_new.py':'0'*64}),
                dict(tests_run=4),dict(skipped=1),dict(exit_code=1),dict(test_review_sha256='0'*64)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                q.next_stage(self.p,dict(red=self.r,test_review=self.review,green={**self.g,**change}))

    def test_sensitivity_is_same_green_commit_and_covers_all_acceptance_ids(self):
        for change in (dict(commit_sha='2'*40),dict(manifest_sha256='0'*64),dict(positive_sha256='0'*64),dict(controls=[])):
            evidence=self.proofs();evidence['sensitivity']={**self.m,**change}
            with self.subTest(change=change),self.assertRaises(ValueError):q.qualify_sensitivity(self.p,evidence)
        for change in (dict(criteria=['A01']),dict(exit_code=0),dict(errors=1),dict(tests_run=4),
                dict(changed_files=['tests/test_new.py']),dict(changed_files=['.github/workflows/ci.yml']),
                dict(tests={}),dict(failures=[dict(path='tests/test_new.py',method='test_new',phase='import',kind='exception')])):
            evidence=self.proofs();evidence['sensitivity']={**self.m,'controls':[{**self.m['controls'][0],**change}]}
            with self.subTest(change=change),self.assertRaises(ValueError):q.qualify_sensitivity(self.p,evidence)

    def test_unknown_fields_legacy_plan_or_bool_counts_are_rejected(self):
        for change in (dict(version=1),dict(waive_sensitivity=True),dict(product_files=['tests/test_new.py']),
                dict(product_files=['tests/harness.js']),dict(product_files=['.github/workflows/other.yml']),
                dict(protected_files=['tests/test_new.py']),dict(criteria=[])):
            with self.subTest(change=change),self.assertRaises(ValueError):q.next_stage({**self.p,**change},{})
        with self.assertRaises(ValueError):q.next_stage(self.p,dict(red={**self.r,'tests_run':True}))

    def test_claimed_criteria_need_their_frozen_assertion_witnesses(self):
        proof=self.proofs();proof['sensitivity']=copy.deepcopy(self.m)
        proof['sensitivity']['controls'][0]['failures']=proof['sensitivity']['controls'][0]['failures'][:1]
        with self.assertRaises(ValueError):q.qualify_sensitivity(self.p,proof)
        changed={**self.p,'product_files':['app/other.js']}
        with self.assertRaises(ValueError):q.next_stage(changed,self.proofs())


if __name__=='__main__':unittest.main()
