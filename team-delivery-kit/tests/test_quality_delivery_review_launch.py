"""Offline adapter fixtures; not a native reviewer or an autonomy qualification."""
import copy
import unittest
from unittest.mock import patch
from broker import quality_delivery_review_launch as launch
import test_quality_delivery_review_validation as fixtures


class DeliveryReviewLaunchTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryReviewValidationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.request=f.request
        with patch.object(fixtures.validation.validation_job,'run',side_effect=f.job):
            f.call()
        self.b.QUALITY_REVIEW_WORKER_IMAGE='sha256:'+'8'*64
        self.b.MODEL_NETWORK=self.b.PREFIX+'_model';previous=self.b.docker;self.effects=[]
        self.image=dict(Id=self.b.QUALITY_REVIEW_WORKER_IMAGE,Config=dict(User='10000:10000',Env=[],Volumes=None,
            Labels={'delivery-kit.component':'quality-author-worker'}))
        self.network=dict(Name=self.b.MODEL_NETWORK,Internal=True,Labels={'com.docker.compose.project':self.b.PREFIX})
        def docker(method,path,payload=None):
            if method!='GET':self.effects.append((method,path,payload))
            if path=='/images/'+self.b.QUALITY_REVIEW_WORKER_IMAGE+'/json':return copy.deepcopy(self.image)
            if path=='/networks/'+self.b.MODEL_NETWORK:return copy.deepcopy(self.network)
            return previous(method,path,payload)
        self.b.docker=docker

    def test_worker_mounts_only_immutable_candidate_and_uses_separate_phase(self):
        self.assertTrue(launch.owns(self.b,self.request));launch.prepare_worker(self.b,self.request)
        p=launch.payload(self.b,self.request);c,_,_=launch.context_for(self.b,self.request)
        self.assertEqual(p['HostConfig']['Mounts'],[dict(Type='volume',Source=c['snapshot_volume'],Target='/delivery',ReadOnly=True)])
        self.assertTrue(p['HostConfig']['ReadonlyRootfs']);self.assertFalse(p['HostConfig']['Binds'])
        self.assertEqual(p['Labels']['com.docker.compose.project'],self.b.PREFIX+'-tests')
        spec=launch.transport_spec(self.b,self.request)
        self.assertEqual(spec['quality_phase_config']['phase'],'delivery_review_v2')
        self.assertEqual(spec['editable_paths'],[]);self.assertEqual(spec['test_commands'],[])
        self.assertFalse(self.effects)

    def test_unverified_or_altered_validation_never_yields_worker_payload(self):
        with self.b.db() as con:con.execute("DELETE FROM validation_jobs WHERE json_extract(identity,'$.kind')='delivery_review'")
        with self.assertRaises(ValueError):launch.payload(self.b,self.request)
        self.assertFalse(self.effects)

    def test_no_launch_before_validation_or_when_disabled(self):
        with self.b.db() as con:con.execute('DELETE FROM quality_delivery_review_validations')
        with self.assertRaises(ValueError):launch.prepare_worker(self.b,self.request)
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=False
        with self.assertRaises(ValueError):launch.payload(self.b,self.request)
        self.assertFalse(self.effects)

    def test_foreign_or_terminal_native_task_cannot_prepare_worker(self):
        self.f.f.current['status']='completed'
        with self.assertRaises(ValueError):launch.prepare_worker(self.b,self.request)
        self.assertFalse(self.effects)

    def test_credentials_anonymous_volumes_or_external_network_cannot_enter_worker(self):
        for changes in (dict(User='0:0'),dict(Env=['OPENROUTER_API_KEY=fixture']),dict(Volumes={'/data':{}})):
            original=copy.deepcopy(self.image['Config']);self.image['Config'].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):launch.payload(self.b,self.request)
            self.image['Config']=original
        self.network['Internal']=False
        with self.assertRaises(ValueError):launch.payload(self.b,self.request)
        self.assertFalse(self.effects)

    def test_frozen_prompt_bound_to_native_task_and_capsule(self):
        task=launch.current(self.b,self.request);c,assignment,_=launch.context_for(self.b,self.request)
        frame=dict(method='session/prompt',params={})
        result=launch.prompt(self.b,frame,assignment['requirements'],task,None)
        self.assertIn(c['commit_sha'],str(result));self.assertIn(c['manifest_sha256'],str(result))
        with self.assertRaises(ValueError):launch.prompt(self.b,frame,assignment['requirements'],task,'rerun Red')
        with self.assertRaises(ValueError):launch.prompt(self.b,frame,{**assignment['requirements'],'description':'drift'},task,None)


if __name__=='__main__':unittest.main()
