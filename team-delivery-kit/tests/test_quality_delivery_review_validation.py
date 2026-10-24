"""Durable native/job fixtures; never a live reviewer or delivery approval."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from docker_grouping import grouped_create
from broker import quality_delivery_review_validation as validation
import test_quality_delivery_review_handoff as fixtures
import test_validation_job as jobs

FIXED_JOB_RUN=validation.validation_job.run


class DeliveryReviewValidationTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryReviewHandoffTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.b=f.b
        f.native_task();self.grant=f.admit();self.request=self.grant['request_id'];self.jobs=0;self.mutate=None
        self.b.QUALITY_DELIVERY_REVIEW_JOB_IMAGE='sha256:'+'6'*64;previous=self.b.docker
        self.image=dict(Id=self.b.QUALITY_DELIVERY_REVIEW_JOB_IMAGE,Config=dict(User='10000:10000',Env=[],Volumes=None,
            Entrypoint=['python','/opt/quality/quality_delivery_review_job.py'],
            Labels={'delivery-kit.component':'quality-delivery-review-job','delivery-kit.quality-operations':'validate_delivery_review_v2'}))
        def docker(method,path,payload=None):
            if path=='/images/'+self.b.QUALITY_DELIVERY_REVIEW_JOB_IMAGE+'/json':return copy.deepcopy(self.image)
            return previous(method,path,payload)
        self.b.docker=docker

    def job(self,b,task,kind,payload):
        self.jobs+=1;self.assertEqual(task,self.f.task);self.assertEqual(kind,'delivery_review')
        context,_=validation.load(b,self.request);plan=context['plan'];green=context['evidence']['green']
        report=dict(operation='full_suite_delivery_review_observation_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            contract_sha256=plan['contract_sha256'],plan_sha256=validation.quality.digest(plan),task_id=task,
            request_id=self.request,reviewer=plan['reviewer'],quality_evidence_sha256=validation.quality.digest(context['evidence']),
            base_manifest_sha256=context['base']['manifest_sha256'],manifest_sha256=green['manifest_sha256'],commit_sha=green['commit_sha'],
            suite={k:copy.deepcopy(green[k]) for k in validation.quality.suite_fields(plan)},snapshot_unchanged=True,
            captured_output_sha256='c'*64,captured_output_bytes=0,native_identity_verified=False,job_receipt_verified=False,
            tests_approved=False,merge_authorized=False,delivery_approval=False)
        if self.mutate:self.mutate(report)
        p=grouped_create('POST','/containers/create?name=validation',payload,b.PREFIX)
        key=validation.green.digest(dict(task=task,kind=kind,payload=p))
        expected={**p,'Labels':{**p['Labels'],'delivery-kit.owner':b.OWNER,
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind=kind,name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        output=json.dumps(report);result=dict(container_id='7'*64,exit_code=0,output=output,
            output_sha256=hashlib.sha256(output.encode()).hexdigest(),validation_job_key=key,
            validation_contract_sha256=validation.green.digest(identity),approval=False)
        with b.db() as con:con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
            (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='7'*64,result=result))))
        return result

    def call(self):return validation.observe(self.b,self.request)

    def test_exact_review_owned_job_yields_validation_facts_not_a_verdict(self):
        with patch.object(validation.validation_job,'run',side_effect=self.job):result=self.call()
        self.assertEqual(result['stage'],'review_validation_observed')
        facts=result['validation'];self.assertEqual(facts['task_id'],self.f.task)
        self.assertEqual(facts['request_id'],self.request);self.assertEqual(facts['network'],'none')
        self.assertEqual(facts['snapshot_mount'],'readonly');self.assertEqual(len(facts['job_receipt_sha256']),64)
        self.assertFalse(result['delivery_approval']);self.assertFalse(result['merge_authorized'])
        context,_=validation.load(self.b,self.request)
        p=context['payload'];self.assertEqual(p['HostConfig']['NetworkMode'],'none')
        self.assertEqual(p['Entrypoint'],['python','/opt/quality/quality_delivery_review_job.py'])
        self.assertEqual({m['Target'] for m in p['HostConfig']['Mounts']},{'/base','/snapshot'})
        self.assertTrue(all(m['ReadOnly'] for m in p['HostConfig']['Mounts']))
        with patch.object(validation.validation_job,'run',side_effect=AssertionError('no second validation')):
            self.assertEqual(self.call(),result)

    def test_unjournaled_success_cannot_be_used_as_reviewer_validation(self):
        with patch.object(validation.validation_job,'run',return_value=dict(exit_code=0,output='claimed success')):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],self.b.QUALITY_CTO)
        self.assertFalse(result['incident']['automatic_retry'])

    def test_partial_suite_wrong_task_sha_or_claimed_authority_is_rejected(self):
        changes=[lambda r:r['suite'].update(tests_run=1),lambda r:r['suite'].update(skipped=1),
            lambda r:r.update(task_id=self.f.task+'x'),lambda r:r.update(commit_sha='0'*40),
            lambda r:r.update(quality_evidence_sha256='0'*64),lambda r:r.update(job_receipt_verified=True),
            lambda r:r.update(native_identity_verified=True),lambda r:r.update(delivery_approval=True)]
        for n,change in enumerate(changes):
            self.mutate=change
            with self.subTest(case=n),patch.object(validation.validation_job,'run',side_effect=self.job):
                result=self.call();self.assertEqual(result['stage'],'technical_blocked')
            with self.b.db() as con:
                con.execute('DELETE FROM quality_delivery_review_validations')
                con.execute("DELETE FROM validation_jobs WHERE json_extract(identity,'$.kind')='delivery_review'")

    def test_pending_job_resumes_same_request_payload_and_deadline(self):
        with patch.object(validation.validation_job,'run',side_effect=validation.validation_job.Pending('same job')) as run:
            for _ in range(2):
                with self.assertRaises(validation.validation_job.Pending):self.call()
        self.assertEqual(run.call_args_list[0],run.call_args_list[1])
        before=validation.load(self.b,self.request)
        with patch.object(validation.validation_job,'run',side_effect=self.job):result=self.call()
        after=validation.load(self.b,self.request)
        self.assertEqual(before[0],after[0]);self.assertEqual(before[1]['deadline'],after[1]['deadline'])
        self.assertEqual(result['stage'],'review_validation_observed')

    def test_stale_native_execution_or_snapshot_cannot_launch_a_validation_job(self):
        self.f.current['status']='completed'
        with patch.object(validation.validation_job,'run') as run,self.assertRaises(ValueError):self.call()
        run.assert_not_called()
        self.f.current['status']='running';self.f.f.f.f.volume['CreatedAt']='recreated'
        with patch.object(validation.validation_job,'run') as run,self.assertRaises(ValueError):self.call()
        run.assert_not_called()

    def test_wrong_image_entrypoint_or_credential_environment_cannot_launch(self):
        for config in (dict(User='0:0'),dict(Entrypoint=['sh']),dict(Volumes={'/opt/data':{}}),dict(Env=['API_KEY=private-fixture'])):
            original=copy.deepcopy(self.image['Config']);self.image['Config'].update(config)
            with self.subTest(config=config),patch.object(validation.validation_job,'run') as run,self.assertRaises(ValueError):self.call()
            run.assert_not_called();self.image['Config']=original

    def test_lost_source_observation_expires_without_recreating_the_job(self):
        with patch.object(validation.validation_job,'run',side_effect=validation.validation_job.Pending('same job')):
            with self.assertRaises(validation.validation_job.Pending):self.call()
        _,before=validation.load(self.b,self.request)
        with patch.object(validation.time,'time',return_value=before['deadline']+1),\
                patch.object(validation,'provenance',side_effect=TimeoutError('native unavailable')):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertFalse(result['incident']['automatic_retry'])

    def test_maintenance_and_disabled_feature_prevent_job_effects(self):
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=False
        with patch.object(validation.validation_job,'run') as run,self.assertRaises(ValueError):self.call()
        run.assert_not_called();self.b.QUALITY_DELIVERY_REVIEW_ENABLED=True
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operator','sealed',json.dumps(dict(stage='sealed'))))
        with patch.object(validation.validation_job,'run') as run,self.assertRaises(validation.validation_job.Pending):self.call()
        run.assert_not_called()

    def test_registered_validation_kind_keeps_same_job_after_unknown_create_and_cleanup(self):
        f=jobs.ValidationJobTests();f.setUp();self.addCleanup(f.doCleanups);f.uncertain_create=True
        with self.assertRaises(validation.validation_job.Pending):FIXED_JOB_RUN(f.b,jobs.TASK,'delivery_review',f.payload,now=1)
        with self.assertRaises(validation.validation_job.Pending):FIXED_JOB_RUN(f.b,jobs.TASK,'delivery_review',f.payload,now=2)
        f.info['State']['Status']='exited'
        result=FIXED_JOB_RUN(f.b,jobs.TASK,'delivery_review',f.payload,now=3)
        f.info=None
        self.assertEqual(FIXED_JOB_RUN(f.b,jobs.TASK,'delivery_review',f.payload,now=4),result)
        self.assertEqual(sum(m=='POST' and '/create' in p for m,p in f.calls),1)


if __name__=='__main__':unittest.main()
