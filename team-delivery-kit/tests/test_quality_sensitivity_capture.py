"""Durable native/job fixtures; not real-agent sensitivity qualification."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from docker_grouping import grouped_create
from broker import quality_sensitivity_capture as capture
import test_quality_green_capture as fixtures


class SensitivityCaptureTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.GreenCaptureTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.b=f.b;self.request=f.request
        f.receipt['candidate']=dict(git_proof=dict(changed_paths=['app.py','tests/test_new.py']))
        self.operation_supported=True;previous=self.b.docker
        def docker(method,path,payload=None):
            result=previous(method,path,payload)
            if path=='/images/'+self.b.QUALITY_GREEN_JOB_IMAGE+'/json' and self.operation_supported:
                result['Config']['Labels']['delivery-kit.quality-operations']='observe_reversion_v2'
            return result
        self.b.docker=docker
        with patch.object(capture.green.validation_job,'run',side_effect=f.job):f.call()
        self.jobs=0;self.mutate=None

    def job(self,b,task,kind,payload):
        self.jobs+=1;self.assertEqual(kind,'sensitivity')
        context,_=capture.load(b,self.request);plan=context['plan'];passing=context['evidence']['green']
        failures=context['evidence']['red']['failures'];witnesses={(v['path'],v['method']) for v in failures}
        covered=sorted(c for c,tests in plan['criterion_tests'].items()
            if any((t['path'],t['method']) in witnesses for t in tests))
        control=dict(id='revert_product_to_reviewed_red',criteria=covered,changed_files=context['changed_product_paths'],
            tests=passing['tests'],suite_complete=True,tests_run=passing['tests_run'],skipped=0,errors=0,exit_code=1,failures=failures)
        facts=dict(operation='observed_sensitivity_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            contract_sha256=plan['contract_sha256'],plan_sha256=capture.quality.digest(plan),
            green_sha256=capture.quality.digest(passing),positive_sha256=capture.quality.digest(passing),
            manifest_sha256=context['manifest_sha256'],commit_sha=context['commit_sha'],controls=[control])
        missing=sorted(set(plan['criteria'])-set(covered))
        report=dict(operation='post_green_reversion_observation_v2',sensitivity=facts,coverage_complete=not missing,
            missing_criteria=missing,reviewed_manifest_sha256=context['evidence']['red']['manifest_sha256'],
            captured_output_sha256='b'*64,snapshot_unchanged=True,tests_unchanged=True,
            execution_authorized=False,merge_authorized=False,delivery_approval=False)
        if self.mutate:self.mutate(report)
        p=grouped_create('POST','/containers/create?name=validation',payload,b.PREFIX)
        key=capture.green.digest(dict(task=task,kind=kind,payload=p))
        expected={**p,'Labels':{**p['Labels'],'delivery-kit.owner':b.OWNER,
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind=kind,name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        output=json.dumps(report)
        result=dict(container_id='8'*64,exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            validation_job_key=key,validation_contract_sha256=capture.green.digest(identity),approval=False)
        with b.db() as con:con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
            (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='8'*64,result=result))))
        return result

    def call(self):return capture.observe(self.b,self.request)

    def test_exact_full_inventory_control_advances_only_to_independent_review(self):
        with patch.object(capture.validation_job,'run',side_effect=self.job):result=self.call()
        self.assertEqual(result['stage'],'awaiting_independent_delivery_review');self.assertFalse(result['delivery_approval'])
        context,_=capture.load(self.b,self.request)
        mounts=context['payload']['HostConfig']['Mounts']
        self.assertEqual({m['Target'] for m in mounts},{'/base','/candidate','/snapshot'})
        self.assertTrue(all(m['ReadOnly'] for m in mounts))
        self.assertEqual(context['payload']['HostConfig']['NetworkMode'],'none')
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('no duplicate negative execution')):
            self.assertEqual(self.call(),result)

    def test_wrong_commit_test_skip_or_fictitious_coverage_is_rejected(self):
        for field,value in [('commit_sha','f'*40),('positive_sha256','e'*64)]:
            with self.subTest(field=field):
                self.mutate=lambda report:report['sensitivity'].update({field:value})
                with patch.object(capture.validation_job,'run',side_effect=self.job):
                    self.assertEqual(self.call()['stage'],'technical_blocked')
                with self.b.db() as con:
                    con.execute('DELETE FROM quality_sensitivity_captures')
                    con.execute("DELETE FROM validation_jobs WHERE json_extract(identity,'$.kind')='sensitivity'")
        self.mutate=lambda report:report['sensitivity']['controls'][0].update(skipped=1)
        with patch.object(capture.validation_job,'run',side_effect=self.job):
            self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_pending_job_keeps_context_and_deadline_then_observes_same_operation(self):
        with patch.object(capture.validation_job,'run',side_effect=capture.validation_job.Pending('same handle')):
            with self.assertRaises(capture.validation_job.Pending):self.call()
        before=capture.load(self.b,self.request)
        with patch.object(capture.validation_job,'run',side_effect=self.job):result=self.call()
        after=capture.load(self.b,self.request)
        self.assertEqual(before[0],after[0]);self.assertEqual(before[1]['deadline'],after[1]['deadline'])
        self.assertEqual(result['stage'],'awaiting_independent_delivery_review')

    def test_image_without_explicit_operation_support_cannot_create_a_job(self):
        self.operation_supported=False
        with patch.object(capture.validation_job,'run') as job,self.assertRaises(ValueError):self.call()
        job.assert_not_called()

    def test_source_outage_after_observation_budget_is_visible_not_an_infinite_poll(self):
        with patch.object(capture.validation_job,'run',side_effect=capture.validation_job.Pending('original')):
            with self.assertRaises(capture.validation_job.Pending):self.call()
        _,state=capture.load(self.b,self.request)
        with patch.object(capture.time,'time',return_value=state['deadline']+1),\
                patch.object(capture,'provenance',side_effect=OSError('source unavailable')):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['incident']['category'],'sensitivity_source_observation_deadline')

    def test_partial_witnesses_are_preserved_in_cto_incident_not_retried(self):
        original=capture.provenance(self.b,self.request)
        context=copy.deepcopy(original);plan=context['plan'];plan['criteria'].append('A02')
        plan['criterion_tests']['A02']=[dict(path='tests/test_new.py',method='test_other')]
        evidence=context['evidence']
        for value in evidence.values():value['plan_sha256']=capture.quality.digest(plan)
        evidence['test_review'].update(criteria=plan['criteria'],red_sha256=capture.quality.digest(evidence['red']))
        evidence['green'].update(red_sha256=capture.quality.digest(evidence['red']),
            test_review_sha256=capture.quality.digest(evidence['test_review']))
        with patch.object(capture,'provenance',side_effect=lambda *_:copy.deepcopy(context)),\
                patch.object(capture.validation_job,'run',side_effect=self.job):result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],context['cto'])
        self.assertEqual(result['incident']['missing_criteria'],['A02']);self.assertFalse(result['incident']['automatic_retry'])
        self.assertIn('observation',result)
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('never repeat incomplete coverage')):
            self.assertEqual(self.call(),result)


if __name__=='__main__':unittest.main()
