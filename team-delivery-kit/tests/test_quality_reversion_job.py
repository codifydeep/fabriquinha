"""Actual full-suite reversion, synthetic review/identities; not native approval."""
import hashlib
import json
import unittest
import quality_reversion_job as reversion
from broker import quality_lifecycle_v2 as quality
import test_quality_green_observation as fixtures


class ReversionJobTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.GreenObservationTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f

    def prepare(self):
        self.f.prepare_context()
        self.green=self.f.call()['green']
        self.evidence=dict(red=self.f.red,test_review=self.f.review,green=self.green)

    def call(self):
        f=self.f
        return reversion.run(f.f.base,f.green,f.f.snapshot,f.f.plan,f.task,f.f.prepared['base_manifest_sha256'],
            f.manifest,f.f.prepared['manifest_sha256'],self.evidence)

    def test_reversion_reexecutes_full_frozen_suite_and_witnesses_the_criterion(self):
        self.prepare();before={p:p.read_bytes() for p in self.f.f.root.rglob('*') if p.is_file()}
        report=self.call();facts=report['sensitivity']
        self.assertTrue(report['coverage_complete']);self.assertEqual(report['missing_criteria'],[])
        self.assertEqual(facts['controls'][0]['tests_run'],2)
        self.assertEqual(facts['controls'][0]['criteria'],['A01'])
        self.assertEqual(facts['controls'][0]['changed_files'],['app.py'])
        self.assertEqual(facts['commit_sha'],self.green['commit_sha'])
        quality.qualify_sensitivity(self.f.f.plan,{**self.evidence,'sensitivity':facts})
        self.assertFalse(report['delivery_approval'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.f.f.root.rglob('*') if p.is_file()})

    def test_partial_criterion_witnesses_are_visible_and_never_qualify_all_controls(self):
        f=self.f;extra=b'\n def test_already_nonnegative(self):self.assertGreaterEqual(app.VALUE,0)\n'
        path=f.f.snapshot/'tests/test_new.py';raw=path.read_bytes()+extra
        path.chmod(0o600);path.write_bytes(raw);path.chmod(0o400)
        manifest=f.f.snapshot/'manifest.json';data=json.loads(manifest.read_bytes())
        data['files']['tests/test_new.py']=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        manifest.chmod(0o600);manifest.write_bytes(json.dumps(data,sort_keys=True,separators=(',',':')).encode());manifest.chmod(0o400)
        f.f.prepared['manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
        f.replace('tests/test_new.py',raw)
        f.f.plan['criteria'].append('A02');f.f.plan['criterion_tests']['A02']=[dict(path='tests/test_new.py',method='test_already_nonnegative')]
        self.prepare();report=self.call()
        self.assertFalse(report['coverage_complete']);self.assertEqual(report['missing_criteria'],['A02'])
        self.assertEqual(report['sensitivity']['controls'][0]['tests_run'],3)
        with self.assertRaises(ValueError):quality.qualify_sensitivity(f.f.plan,{**self.evidence,'sensitivity':report['sensitivity']})

    def test_changed_reviewed_tests_cannot_be_reclassified_as_a_negative(self):
        self.prepare();path=self.f.f.snapshot/'tests/test_new.py';path.chmod(0o600);path.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.call()

    def test_other_candidate_sha_manifest_or_green_identity_is_not_accepted(self):
        self.prepare();self.evidence['green']['manifest_sha256']='f'*64
        with self.assertRaises(ValueError):self.call()

    def test_legacy_red_receipt_is_not_post_green_control_execution(self):
        self.prepare();self.evidence.pop('green')
        with self.assertRaises(ValueError):self.call()


if __name__=='__main__':unittest.main()
