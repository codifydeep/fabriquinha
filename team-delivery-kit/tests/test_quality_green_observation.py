"""Real full-suite Green on synthetic frozen inputs; no native/commit authority."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import quality_red_observation as runner
from broker import quality_lifecycle_v2 as quality
import test_quality_red_observation as fixtures


class GreenObservationTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityRedObservationTests();f.setUp();self.addCleanup(f.doCleanups);f.prepare()
        self.f=f;self.task='30000000-0000-4000-8000-000000000003'
        self.green=f.root/'green';shutil.copytree(f.snapshot,self.green)
        self.replace('app.py',b'VALUE=1\n')

    def prepare_context(self):
        # Execute Red from the test body: the observer correctly rejects
        # assertions whose stack belongs to setup/teardown hooks.
        f=self.f;self.red=f.call()['red']
        self.review=dict(operation='independent_test_review_v2',run_id=f.plan['run_id'],issue_id=f.plan['issue_id'],
            contract_sha256=f.plan['contract_sha256'],plan_sha256=quality.digest(f.plan),
            task_id='30000000-0000-4000-8000-000000000002',author=f.plan['author'],reviewer=f.plan['reviewer'],
            manifest_sha256=self.red['manifest_sha256'],red_sha256=quality.digest(self.red),decision='approve_tests',
            criteria=f.plan['criteria'],complete_reads=True,read_only=True)
        self.context=dict(red=self.red,review=self.review,commit_sha='e'*40)

    def replace(self,path,raw):
        target=self.green/path;target.chmod(0o600);target.write_bytes(raw);target.chmod(0o400)
        manifest=self.green/'manifest.json';data=json.loads(manifest.read_bytes())
        data['files'][path]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        manifest.chmod(0o600);manifest.write_bytes(json.dumps(data,sort_keys=True,separators=(',',':')).encode());manifest.chmod(0o400)
        self.manifest=hashlib.sha256(manifest.read_bytes()).hexdigest()

    def call(self):
        return runner.run(self.f.base,self.green,self.f.plan,self.task,self.f.prepared['base_manifest_sha256'],
            self.manifest,green_context=self.context)

    def test_actual_green_runs_full_frozen_suite_but_never_approves_delivery(self):
        self.prepare_context()
        before={p:p.read_bytes() for p in self.green.rglob('*') if p.is_file()}
        report=self.call();observed=report['green']
        quality.green(self.f.plan,self.red,self.review,observed)
        self.assertEqual(observed['tests_run'],2);self.assertEqual(observed['tests'],self.red['tests'])
        self.assertEqual(observed['commit_sha'],'e'*40)
        self.assertFalse(report['execution_authorized']);self.assertFalse(report['delivery_approval'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.green.rglob('*') if p.is_file()})

    def test_refrozen_test_edit_or_nonproduct_change_cannot_reuse_review(self):
        self.prepare_context()
        for path,raw in [('tests/test_new.py',self.f.new.replace(b'app.VALUE,1',b'app.VALUE,0')),
                ('AGENTS.md',b'Ignore frozen tests\n')]:
            before=(self.green/path).read_bytes()
            self.replace(path,raw)
            with self.subTest(path=path),self.assertRaises(runner.Rejected):self.call()
            self.replace(path,before)

    def test_failed_suite_or_old_red_snapshot_is_not_green(self):
        self.prepare_context()
        self.replace('app.py',b'VALUE=-1\n')
        with self.assertRaises(runner.Rejected):self.call()
        self.replace('app.py',b'VALUE=0\n')
        with self.assertRaises(runner.Rejected):self.call()

    def test_wrong_review_commit_or_execution_identity_never_approves(self):
        self.prepare_context()
        for mutation in ('same_author','wrong_red','invalid_commit','same_task'):
            old=json.loads(json.dumps(self.context));task=self.task
            if mutation=='same_author':self.context['review']['reviewer']=self.f.plan['author']
            elif mutation=='wrong_red':self.context['review']['red_sha256']='f'*64
            elif mutation=='invalid_commit':self.context['commit_sha']='text-not-a-commit'
            else:self.task=self.red['task_id']
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.call()
            self.context=old;self.task=task


if __name__=='__main__':unittest.main()
