"""Real frozen-suite execution; synthetic identities are not native authority."""
import copy
import json
import unittest
from unittest.mock import patch

import quality_delivery_review_job as job
import quality_reversion_job as reversion
from broker import quality_lifecycle_v2 as quality
import test_quality_green_observation as fixtures


class DeliveryReviewJobTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.GreenObservationTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f

    def prepare(self):
        # Red must execute from the test body, not a setup hook: preserve the
        # observer's distinction between behavioral failures and setup faults.
        f=self.f
        f.prepare_context();green=f.call()['green']
        evidence=dict(red=f.red,test_review=f.review,green=green)
        negative=reversion.run(f.f.base,f.green,f.f.snapshot,f.f.plan,f.task,
            f.f.prepared['base_manifest_sha256'],f.manifest,f.f.prepared['manifest_sha256'],evidence)
        evidence['sensitivity']=negative['sensitivity']
        self.value=dict(operation='validate_delivery_review_v2',plan=f.f.plan,evidence=evidence,
            task_id='60000000-0000-4000-8000-000000000001',
            request_id='60000000-0000-4000-8000-000000000002',reviewer=f.f.plan['reviewer'],
            base_manifest_sha256=f.f.prepared['base_manifest_sha256'],snapshot_manifest_sha256=f.manifest)

    def call(self,value=None):
        return job.run(self.f.f.base,self.f.green,self.value if value is None else value)

    def test_reviewer_executes_the_whole_suite_again_without_approving_anything(self):
        self.prepare()
        before={p:p.read_bytes() for p in self.f.f.root.rglob('*') if p.is_file()}
        with patch.object(job.observer,'run',wraps=job.observer.run) as execute:
            result=self.call()
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[3],self.value['task_id'])
        self.assertEqual(result['suite']['tests_run'],2)
        self.assertEqual(result['suite']['tests'],self.value['evidence']['green']['tests'])
        self.assertEqual(result['task_id'],self.value['task_id'])
        self.assertEqual(result['request_id'],self.value['request_id'])
        self.assertEqual(result['commit_sha'],self.value['evidence']['green']['commit_sha'])
        self.assertEqual(result['quality_evidence_sha256'],quality.digest(self.value['evidence']))
        self.assertEqual(before,{p:p.read_bytes() for p in self.f.f.root.rglob('*') if p.is_file()})
        for key in ('native_identity_verified','job_receipt_verified','tests_approved','merge_authorized','delivery_approval'):
            self.assertIs(result[key],False)
        self.assertNotIn('job_receipt_sha256',result)
        self.assertNotIn('PRIVATE_TEST_DETAIL',json.dumps(result))

    def test_claimed_green_does_not_replace_a_fresh_execution(self):
        self.prepare()
        with patch.object(job.observer,'run',side_effect=ValueError('fresh suite failed')) as execute:
            with self.assertRaises(ValueError):self.call()
        execute.assert_called_once()

    def test_author_or_upstream_task_cannot_be_the_delivery_reviewer(self):
        self.prepare()
        for change in (dict(reviewer=self.value['plan']['author']),dict(reviewer='foreign'),
                *(dict(task_id=self.value['evidence'][k]['task_id']) for k in ('red','test_review','green')),
                dict(task_id='not-native-task'),dict(request_id='not-native-request')):
            with self.subTest(change=change),patch.object(job.observer,'run') as execute:
                with self.assertRaises(ValueError):self.call({**self.value,**change})
                execute.assert_not_called()

    def test_missing_or_stale_quality_evidence_is_rejected_before_execution(self):
        self.prepare()
        for key in ('red','test_review','green','sensitivity'):
            value=copy.deepcopy(self.value);del value['evidence'][key]
            with self.subTest(key=key),patch.object(job.observer,'run') as execute:
                with self.assertRaises(ValueError):self.call(value)
                execute.assert_not_called()
        with patch.object(job.observer,'run') as execute:
            with self.assertRaises(ValueError):self.call({**self.value,'snapshot_manifest_sha256':'0'*64})
            execute.assert_not_called()

    def test_fixed_request_has_no_command_path_subset_or_approval_fields(self):
        self.prepare()
        for change in (dict(command=['sh']),dict(test_paths=['tests/test_new.py']),
                dict(snapshot='/other'),dict(approve=True),dict(operation='observe_green_v2')):
            with self.subTest(change=change),self.assertRaises(ValueError):job.request(json.dumps({**self.value,**change}))
        for raw in ('[]','{}',' '*65537):
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):job.request(raw)

    def test_changed_snapshot_or_frozen_tests_cannot_be_revalidated_as_the_same_delivery(self):
        self.prepare()
        for path in ('app.py','tests/test_old.py','tests/test_new.py'):
            target=self.f.green/path;original=target.read_bytes();target.chmod(0o600)
            try:
                target.write_bytes(original+b'\n# drift\n')
                with self.subTest(path=path),self.assertRaises(ValueError):self.call()
            finally:target.write_bytes(original);target.chmod(0o400)

    def test_partial_or_relabelled_job_output_is_not_a_complete_reviewer_suite(self):
        self.prepare()
        report=job.observer.run(self.f.f.base,self.f.green,self.value['plan'],self.value['task_id'],
            self.value['base_manifest_sha256'],self.value['snapshot_manifest_sha256'],
            green_context=dict(red=self.f.red,review=self.f.review,commit_sha=self.value['evidence']['green']['commit_sha']))
        for key,value in (('tests_run',1),('skipped',1),('task_id',self.f.task),('commit_sha','0'*40)):
            changed=copy.deepcopy(report);changed['green'][key]=value
            with self.subTest(key=key),patch.object(job.observer,'run',return_value=changed),self.assertRaises(ValueError):self.call()


if __name__=='__main__':unittest.main()
