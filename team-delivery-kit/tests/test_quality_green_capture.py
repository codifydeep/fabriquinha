"""Fixed-job and native authority fixtures; not native/model qualification."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from docker_grouping import grouped_create
from broker import quality_green_capture as green
import test_quality_delivery_capture as fixtures


class GreenCaptureTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryCaptureTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.request=f.request
        with patch.object(fixtures.capture.validation_job,'run',side_effect=f.copied):f.call()
        packet=green.delivery.candidate_packet(self.b,self.request)
        self.receipt=dict(commit_sha='a'*40,stage='awaiting_green')
        self.identity=dict(packet=packet)
        p=patch.object(green.binding,'load',side_effect=lambda *_:(copy.deepcopy(self.identity),copy.deepcopy(self.receipt)))
        p.start();self.addCleanup(p.stop)
        self.jobs=0;self.mutate=None

    def job(self,b,task,kind,payload):
        self.jobs+=1;self.assertEqual(kind,'green')
        context,_=green.load(b,self.request);freeze=context['freeze'];plan=context['plan']
        observation=dict(operation='observed_green_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            contract_sha256=plan['contract_sha256'],plan_sha256=green.quality.digest(plan),task_id=task,
            manifest_sha256=context['manifest_sha256'],tests=freeze['frozen_tests'],suite_complete=True,
            tests_run=freeze['red']['tests_run'],skipped=0,errors=0,exit_code=0,failures=[],commit_sha=context['commit_sha'],
            red_sha256=green.quality.digest(freeze['red']),test_review_sha256=green.quality.digest(freeze['test_review']))
        report=dict(operation='full_suite_green_observation_v2',green=observation,
            base_manifest_sha256=context['base']['manifest_sha256'],captured_output_sha256='e'*64,
            captured_output_bytes=0,snapshot_unchanged=True,commit_binding_verified=False,
            execution_authorized=False,delivery_approval=False)
        if self.mutate:self.mutate(report)
        p=grouped_create('POST','/containers/create?name=validation',payload,b.PREFIX)
        key=green.digest(dict(task=task,kind=kind,payload=p))
        expected={**p,'Labels':{**p['Labels'],'delivery-kit.owner':b.OWNER,
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind=kind,name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        output=json.dumps(report)
        result=dict(container_id='9'*64,exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            validation_job_key=key,validation_contract_sha256=green.digest(identity),approval=False)
        with b.db() as con:con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
            (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='9'*64,result=result))))
        return result

    def call(self):return green.observe(self.b,self.request)

    def test_exact_binding_and_durable_fixed_job_yields_only_sensitivity_not_delivery(self):
        with patch.object(green.validation_job,'run',side_effect=self.job):result=self.call()
        self.assertEqual(result['stage'],'awaiting_sensitivity');self.assertFalse(result['green_approved'])
        self.assertFalse(result['delivery_approval'])
        context,_=green.load(self.b,self.request)
        p=context['payload'];request=json.loads(p['Env'][1].split('=',1)[1])
        self.assertEqual(request['green_context']['commit_sha'],self.receipt['commit_sha'])
        self.assertEqual(p['HostConfig']['NetworkMode'],'none')
        self.assertTrue(all(m['ReadOnly'] for m in p['HostConfig']['Mounts']))
        with patch.object(green.validation_job,'run',side_effect=AssertionError('no duplicate Green')):
            self.assertEqual(self.call(),result)

    def test_other_sha_or_skipped_tests_or_fake_job_git_authority_are_rejected(self):
        for key,value in [('commit_sha','b'*40),('skipped',1),('suite_complete',False)]:
            with self.subTest(key=key):
                self.mutate=lambda report:report['green'].update({key:value})
                with patch.object(green.validation_job,'run',side_effect=self.job):result=self.call()
                self.assertEqual(result['stage'],'technical_blocked')
                with self.b.db() as con:
                    con.execute('DELETE FROM quality_green_captures');con.execute("DELETE FROM validation_jobs WHERE job_key IN "
                        "(SELECT job_key FROM validation_jobs WHERE json_extract(identity,'$.kind')='green')")
        self.mutate=lambda report:report.update(commit_binding_verified=True)
        with patch.object(green.validation_job,'run',side_effect=self.job):
            self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_pending_fixed_job_resumes_same_context_and_deadline(self):
        with patch.object(green.validation_job,'run',side_effect=green.validation_job.Pending('observe original')):
            with self.assertRaises(green.validation_job.Pending):self.call()
        before=green.load(self.b,self.request)
        with patch.object(green.validation_job,'run',side_effect=self.job):result=self.call()
        after=green.load(self.b,self.request)
        self.assertEqual(before[0],after[0]);self.assertEqual(before[1]['deadline'],after[1]['deadline'])
        self.assertEqual(result['stage'],'awaiting_sensitivity')

    def test_changed_snapshot_incarnation_prevents_job_creation(self):
        self.f.volume['CreatedAt']='recreated'
        with patch.object(green.validation_job,'run') as job,self.assertRaises(ValueError):self.call()
        job.assert_not_called()

    def test_unregistered_result_cannot_approve_and_is_owned_by_techlead(self):
        with patch.object(green.validation_job,'run',return_value=dict(exit_code=0,output='success')):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],self.b.QUALITY_TECHLEAD)
        self.assertFalse(result['incident']['automatic_retry'])

    def test_source_outage_expires_to_incident_without_restarting_green(self):
        with patch.object(green.validation_job,'run',side_effect=green.validation_job.Pending('original')):
            with self.assertRaises(green.validation_job.Pending):self.call()
        _,state=green.load(self.b,self.request)
        with patch.object(green.time,'time',return_value=state['deadline']+1),\
                patch.object(green,'provenance',side_effect=OSError('source unavailable')):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['incident']['category'],'green_source_observation_deadline')


if __name__=='__main__':unittest.main()
