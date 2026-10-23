"""Actual local Python/Node plus controller receipt validators with mocked provenance.

Not a native-agent qualification: identities are synthetic and fixed-job
authentication has its own separate tests. No delivery approval is emitted.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from broker import quality_lifecycle_v2 as quality,quality_green_capture as green_capture
from broker import quality_sensitivity_capture as sensitivity_capture
import quality_red_observation as observer
import quality_reversion_job as reversion
import test_quality_red_observation as fixtures


class MixedObservationTests(unittest.TestCase):
    def prepare(self,*,node_body="test('baseline',()=>assert.equal(2,2));",test_image=None):
        f=fixtures.QualityRedObservationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.node='node_fixture/tests/old.test.cjs'
        self.green_task='30000000-0000-4000-8000-000000000003'
        if test_image is not None:f.spec['test_image']=test_image
        data=("const test=require('node:test');const assert=require('node:assert/strict');"+node_body+'\n').encode()
        for key in ('files','protected_files'):
            f.spec[key].append(self.node)
        if 'required_files' in f.spec:f.spec['required_files'].append(self.node)
        f.old[self.node]=data;f.prepare()
        f.plan['protected_files'].append(self.node)
        f.plan['node_baseline_tests']={self.node:hashlib.sha256(data).hexdigest()}
        return f

    def context(self):
        f=self.f;self.red=f.call()['red']
        self.review=dict(operation='independent_test_review_v2',run_id=f.plan['run_id'],issue_id=f.plan['issue_id'],
            contract_sha256=f.plan['contract_sha256'],plan_sha256=quality.digest(f.plan),task_id='30000000-0000-4000-8000-000000000002',
            author=f.plan['author'],reviewer=f.plan['reviewer'],manifest_sha256=self.red['manifest_sha256'],
            red_sha256=quality.digest(self.red),decision='approve_tests',criteria=f.plan['criteria'],complete_reads=True,read_only=True)
        self.candidate=f.root/'candidate';shutil.copytree(f.snapshot,self.candidate)
        path=self.candidate/'app.py';path.chmod(0o600);path.write_bytes(b'VALUE=1\n');path.chmod(0o400)
        manifest=self.candidate/'manifest.json';data=json.loads(manifest.read_bytes())
        data['files']['app.py']=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
        manifest.chmod(0o600);manifest.write_bytes(json.dumps(data,sort_keys=True,separators=(',',':')).encode());manifest.chmod(0o400)
        self.manifest=hashlib.sha256(manifest.read_bytes()).hexdigest()
        self.green_report=observer.run(f.base,self.candidate,f.plan,self.green_task,f.prepared['base_manifest_sha256'],self.manifest,
            green_context=dict(red=self.red,review=self.review,commit_sha='e'*40))
        self.evidence=dict(red=self.red,test_review=self.review,green=self.green_report['green'])

    def test_real_red_freezes_node_baseline_and_green_preserves_case_inventory(self):
        f=self.prepare();self.context();passing=self.evidence['green']
        self.assertEqual(self.red['node_baseline']['tests_run'],1)
        self.assertEqual(self.red['node_baseline']['inventory'],passing['node_baseline']['inventory'])
        self.assertEqual(passing['node_baseline']['manifest_sha256'],self.manifest)
        self.assertNotEqual(self.red['node_baseline']['manifest_sha256'],self.manifest)
        self.assertEqual(quality.next_stage(f.plan,self.evidence),'sensitivity')

    def test_missing_node_proof_or_old_diagnostic_cannot_satisfy_red(self):
        f=self.prepare();red=f.call()['red']
        for change in ('missing','old','wrong_snapshot','skipped'):
            value=copy.deepcopy(red)
            if change=='missing':value.pop('node_baseline')
            elif change=='old':value['node_baseline']['operation']='full_node_baseline_observation_v1'
            elif change=='wrong_snapshot':value['node_baseline']['manifest_sha256']='a'*64
            else:value['node_baseline']['counts']['skipped']=1
            with self.subTest(change=change),self.assertRaises(ValueError):quality.red(f.plan,value)

    def test_node_tests_cannot_be_omitted_or_reclassified_as_editable_product(self):
        f=self.prepare()
        value=copy.deepcopy(f.plan);value.pop('node_baseline_tests')
        with self.assertRaises(ValueError):quality.validate(value)
        value=copy.deepcopy(f.plan);value['protected_files'].remove(self.node);value['product_files'].append(self.node)
        with self.assertRaises(ValueError):quality.validate(value)
        f.plan['node_baseline_tests'][self.node]='0'*64
        with self.assertRaises(observer.Rejected):f.call()

    def test_node_failure_or_skip_is_not_new_behavior_red(self):
        for body in ("test('baseline',()=>assert.equal(2,3));","test.skip('baseline',()=>assert.equal(2,2));"):
            with self.subTest(body=body):
                f=self.prepare(node_body=body)
                with self.assertRaises(observer.Rejected) as caught:f.call()
                self.assertEqual(caught.exception.category,'baseline_node_execution_or_evidence_failed')

    def test_same_count_different_cases_are_rejected_on_green(self):
        self.prepare(node_body="const fs=require('node:fs');test(fs.readFileSync('app.py','utf8').includes('VALUE=0')?'old':'other',()=>assert.equal(2,2));")
        with self.assertRaises(observer.Rejected) as caught:self.context()
        self.assertEqual(caught.exception.category,'baseline_node_execution_or_evidence_failed')

    def test_green_controller_cannot_accept_missing_node_after_fixed_job_provenance(self):
        f=self.prepare();self.context()
        ctx=dict(task_id=self.green_task,plan=f.plan,base=dict(manifest_sha256=f.prepared['base_manifest_sha256']),
            freeze=dict(red=self.red,test_review=self.review,frozen_tests=self.red['tests']),
            commit_sha='e'*40,manifest_sha256=self.manifest,payload={})
        with patch.object(green_capture,'fixed_receipt',return_value={'fixture_provenance':True}):
            self.assertEqual(green_capture.observed(None,ctx,dict(output=json.dumps(self.green_report)))['green'],self.evidence['green'])
            invalid=copy.deepcopy(self.green_report);invalid['green'].pop('node_baseline')
            with self.assertRaises(ValueError):green_capture.observed(None,ctx,dict(output=json.dumps(invalid)))

    def test_direct_green_validator_requires_the_prior_frozen_node_inventory(self):
        f=self.prepare();self.context()
        red=copy.deepcopy(self.red);red.pop('node_baseline')
        review=copy.deepcopy(self.review);review['red_sha256']=quality.digest(red)
        green=copy.deepcopy(self.evidence['green'])
        green.update(red_sha256=quality.digest(red),test_review_sha256=quality.digest(review))
        with self.assertRaises(ValueError):quality.green(f.plan,red,review,green)

    def test_reversion_reexecutes_node_and_controller_checks_control_snapshot(self):
        f=self.prepare();self.context()
        report=reversion.run(f.base,self.candidate,f.snapshot,f.plan,self.green_task,f.prepared['base_manifest_sha256'],
            self.manifest,f.prepared['manifest_sha256'],self.evidence)
        control=report['sensitivity']['controls'][0]
        self.assertEqual(control['node_baseline']['manifest_sha256'],self.red['manifest_sha256'])
        self.assertEqual(control['node_baseline']['inventory'],self.evidence['green']['node_baseline']['inventory'])
        ctx=dict(task_id=self.green_task,payload={},plan=f.plan,evidence=self.evidence,manifest_sha256=self.manifest,
            commit_sha='e'*40,changed_product_paths=['app.py'])
        with patch.object(green_capture,'fixed_receipt',return_value={'fixture_provenance':True}):
            self.assertTrue(sensitivity_capture.observed(None,ctx,dict(output=json.dumps(report)))['coverage_complete'])
            invalid=copy.deepcopy(report)
            invalid['sensitivity']['controls'][0]['node_baseline']['manifest_sha256']=self.manifest
            with self.assertRaises(ValueError):sensitivity_capture.observed(None,ctx,dict(output=json.dumps(invalid)))


if __name__=='__main__':unittest.main()
