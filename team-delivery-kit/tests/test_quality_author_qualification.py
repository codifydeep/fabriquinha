"""Failure observation must prove terminal process and retirement, not timeout."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qualify_quality_author_workspace as qualifier
from broker import quality_author_worker
from types import SimpleNamespace


class QualificationFailureTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.namespace='delivery-kit-test'
        self.operation='70000000-0000-4000-8000-000000000001'
        self.archive=self.root/'.local-test/backups'/('quality-author-docker-'+self.operation)
        self.archive.mkdir(parents=True)
        (self.archive/'operation.json').write_text(json.dumps(dict(operation=self.operation,worker_image=None,volumes={})))
        self.p=patch.object(qualifier,'ROOT',self.root);self.p.start();self.addCleanup(self.p.stop)

    def record(self,phase,code):
        name=self.namespace+'-author-probe-'+self.operation[:8]+'-'+phase
        (self.archive/(phase+'-intent.json')).write_text(json.dumps(dict(argv=['docker','run','--name',name])))
        (self.archive/(phase+'-result.json')).write_text(json.dumps(dict(exit_code=code)))
        return name

    def test_nonzero_result_and_exact_retired_helper_records_failure_not_success(self):
        name=self.record('seed',1)
        with patch.object(qualifier,'await_retirement') as observe:
            result=qualifier.observe_failure(self.namespace,self.operation)
        observe.assert_called_once_with(name)
        self.assertEqual(result['status'],'failed');self.assertFalse(result['delivery_approval'])
        self.assertEqual(json.loads((self.archive/'result.json').read_text()),result)

    def test_missing_or_still_live_helper_result_never_closes_unknown_outcome(self):
        with patch.object(qualifier,'await_retirement'):
            with self.assertRaises(FileNotFoundError):qualifier.observe_failure(self.namespace,self.operation)
        self.record('seed',1)
        with patch.object(qualifier,'await_retirement',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):qualifier.observe_failure(self.namespace,self.operation)
        self.assertFalse((self.archive/'result.json').exists())

    def test_green_probe_selection_copies_frozen_tests_but_only_unlocks_product(self):
        import test_quality_red_observation as red
        f=red.QualityRedObservationTests();f.setUp();self.addCleanup(f.doCleanups);f.prepare()
        volumes=dict(base='owned-base',work='owned-work',previous='owned-snapshot')
        context=qualifier.workspace_context(f,volumes,'implementation_v2')
        self.assertEqual(context['selection']['editable_paths'],['/workspace/app.py'])
        self.assertEqual(context['selection']['frozen_seed']['test_sha256'],f.prepared['test_sha256'])
        b=SimpleNamespace(QUALITY_PREP_IMAGE='sha256:'+'a'*64,OWNER='owned')
        seed=quality_author_worker.payload(b,context,'seed')
        self.assertIn(dict(Type='volume',Source='owned-snapshot',Target='/previous',ReadOnly=True),seed['HostConfig']['Mounts'])
        lock=quality_author_worker.payload(b,context,'lock')
        self.assertEqual(json.loads(lock['Env'][0].split('=',1)[1]),['app.py'])
        self.assertFalse(any(m['Target']=='/previous' for m in lock['HostConfig']['Mounts']))

    def test_unknown_qualification_phase_is_not_a_tests_only_fallback(self):
        with self.assertRaises(ValueError):qualifier.workspace_context(None,{},'implementation')

    def test_fixture_snapshot_keeps_real_copier_uid_without_opening_permissions(self):
        text=qualifier.fixture_dockerfile('owned-prep:1',True)
        self.assertIn('COPY --chown=10000:10000 previous /previous',text)
        self.assertNotIn('chmod',text)

    def test_postcopy_only_mounts_inputs_readonly_and_has_no_agent_command(self):
        import test_quality_red_observation as red
        f=red.QualityRedObservationTests();f.setUp();self.addCleanup(f.doCleanups);f.prepare()
        p=qualifier.postcopy_payload(f,dict(base='base',work='work',previous='old',delivered='new'))
        self.assertEqual(p['Cmd'],['/opt/quality/quality_green_job.py'])
        self.assertEqual(p['User'],'10000:10000')
        self.assertEqual(p['HostConfig']['Mounts'],[
            dict(Type='volume',Source='base',Target='/base',ReadOnly=True),
            dict(Type='volume',Source='old',Target='/reviewed',ReadOnly=True),
            dict(Type='volume',Source='work',Target='/workspace',ReadOnly=True),
            dict(Type='volume',Source='new',Target='/snapshot')])
        request=json.loads(p['Env'][0].split('=',1)[1])
        self.assertEqual(request['frozen_tests'],{**f.plan['baseline_tests'],**f.prepared['test_sha256']})
        self.assertEqual(request['operation'],'snapshot_after_implementation_v2')


if __name__=='__main__':unittest.main()
