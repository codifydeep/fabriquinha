"""Operational pause is durable; not a second lifecycle for delivery cards."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.effects import write_json, Journal, Pending, EffectBlocked
from fabriquinha.operations import Control, ActivityPaused, doctor
from fabriquinha.executor import seal_validation
from fabriquinha.quality import CONTROL_CONTRACT
from fabriquinha.profile_policy import contract as profile_contract
from test_delivery_core import configuration


class OperationalControl(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.project=Project.parse(configuration())
        self.control=Control(self.root,self.project)

    def test_pause_survives_new_process_object_and_has_no_expiry(self):
        self.assertFalse(self.control.read()['paused'])
        first=self.control.pause()
        self.assertEqual(self.control.pause(),first)
        again=Control(self.root,self.project)
        self.assertTrue(again.read()['paused'])
        with patch('fabriquinha.operations.time.time',return_value=first['requested_at']+24*3600):
            self.assertTrue(again.read()['paused'])
        self.assertEqual(again.read()['episode'],first['episode'])
        with self.assertRaises(ActivityPaused):again.ensure()
        self.assertEqual((self.root/'control.json').stat().st_mode & 0o777,0o600)

    def test_resume_is_scoped_and_new_pause_rejects_old_authority(self):
        old=self.control.pause()['episode']
        with self.assertRaises(ValueError):self.control.resume('wrong')
        self.control.resume(old);self.control.ensure()
        current=self.control.pause()['episode'];self.assertNotEqual(current,old)
        with self.assertRaises(ValueError):self.control.resume(old)
        self.assertTrue(self.control.read()['paused'])

    def test_corrupt_or_different_project_marker_fails_closed(self):
        value=self.control.pause();value['project']='other'
        write_json(self.root/'control.json',value)
        self.assertTrue(self.control.read()['paused'])
        with self.assertRaises(ActivityPaused):self.control.ensure()
        with self.assertRaises(ValueError):self.control.resume(value['episode'])
        (self.root/'control.json').write_text('broken')
        self.assertTrue(self.control.read()['paused'])
        with self.assertRaises(ValueError):self.control.pause()

    def test_missing_unused_profile_does_not_starve_other_roles(self):
        with patch('fabriquinha.operations.missing_profiles',return_value=['mobile']), \
             patch('fabriquinha.operations.Runner'), \
             patch('fabriquinha.operations.shutil.disk_usage',return_value=Mock(free=2**32)):
            result=doctor(self.project,self.root,Store(self.root/'private'))
        self.assertTrue(result['ready']);self.assertEqual(result['missing_profiles'],['mobile'])

    def test_one_divergent_profile_is_reported_without_a_global_dispatch_fence(self):
        state={'contract':profile_contract(),'errors':[],
            'profiles':{'backend':{'ready':False,'errors':['ProfileConfigDrift']},'lead':{'ready':True,'errors':[]}}}
        with patch('fabriquinha.operations.profile_report',return_value=state), \
             patch('fabriquinha.operations.missing_profiles',return_value=[]), \
             patch('fabriquinha.operations.Runner'),patch('fabriquinha.operations.shutil.disk_usage',return_value=Mock(free=2**32)):
            result=doctor(self.project,self.root,Store(self.root/'private'))
        self.assertTrue(result['ready']);self.assertEqual(result['profiles'],state)

    def test_resource_failure_does_not_claim_success_or_expose_raw_docker_output(self):
        with patch('fabriquinha.operations.missing_profiles',return_value=[]), \
             patch('fabriquinha.operations.Runner',side_effect=ValueError('private diagnostic')), \
             patch('fabriquinha.operations.shutil.disk_usage',return_value=Mock(free=1)):
            result=doctor(self.project,self.root,Store(self.root/'private'))
        self.assertFalse(result['ready'])
        self.assertIn('LowDiskSpace',result['errors'])
        self.assertIn('ValidationRuntimeUnavailable',result['errors'])
        self.assertNotIn('private diagnostic',json.dumps(result))

    def test_real_delivery_cannot_dispatch_without_reserved_networks(self):
        project=Project.parse({**configuration(),'qualification':False,
            'coordination_roles':{'product':'backend','lead':'lead'},
            'delivery_roles':{'tests':'backend','integration':'lead'},'browser_image':'sha256:'+'b'*64})
        store=Store(self.root/'private');bundle=seal_validation(store)
        write_json(self.root/'installation.json',dict(project=project.fingerprint(),validation_bundle=bundle,
            control_contract=CONTROL_CONTRACT,profile_contract=profile_contract()))
        with patch('fabriquinha.operations.missing_profiles',return_value=[]), \
             patch('fabriquinha.operations.Runner'), \
             patch('fabriquinha.operations.docker',return_value=project.browser_image), \
             patch('fabriquinha.operations.shutil.disk_usage',return_value=Mock(free=2**32)), \
             patch('fabriquinha.deployment.deployment_networks',side_effect=EffectBlocked('private Docker error')):
            result=doctor(project,self.root,Store(self.root/'private'))
        self.assertFalse(result['ready'])
        self.assertEqual(result['errors'],['DeploymentNetworksUnavailable'])
        self.assertNotIn('private Docker error',json.dumps(result))

    def test_real_work_requires_a_pinned_bundle_instead_of_silently_using_checkout(self):
        from dataclasses import replace
        project=replace(self.project,qualification=False)
        with patch('fabriquinha.operations.missing_profiles',return_value=[]),patch('fabriquinha.operations.Runner'), \
                patch('fabriquinha.operations.shutil.disk_usage',return_value=Mock(free=2**32)):
            result=doctor(project,self.root,Store(self.root/'private'))
        self.assertFalse(result['ready']);self.assertIn('ValidationBundleRequired',result['errors'])

    def test_pause_before_send_is_retryable_but_unknown_effect_is_never_resent(self):
        clock=[100];journal=Journal(self.root/'effects',clock=lambda:clock[0]);calls=[]
        def send():
            self.control.ensure()
            calls.append('sent')
            raise TimeoutError('ack unknown')
        self.control.pause()
        with self.assertRaises(ActivityPaused):journal.do('fixed',{'scope':'unchanged'},send,lambda:None)
        self.assertEqual(calls,[])
        with self.control.lock():self.control.resume(self.control.read()['episode'])
        clock[0]=1000
        with self.assertRaises(Pending):journal.do('fixed',{'scope':'unchanged'},send,lambda:None)
        self.assertEqual(calls,['sent'])
        clock[0]=1121
        with self.assertRaises(EffectBlocked):journal.do('fixed',{'scope':'unchanged'},send,lambda:None)
        self.assertEqual(calls,['sent'])

    def test_an_observer_interruption_cannot_reclassify_an_already_sent_effect(self):
        journal=Journal(self.root/'effects');calls=[]
        def send():calls.append('sent');raise TimeoutError('accepted; confirmation lost')
        with self.assertRaises(Pending):journal.do('unknown',{},send,lambda:None)
        def interrupted():raise ActivityPaused('observation interrupted')
        with self.assertRaises(ActivityPaused):journal.do('unknown',{},send,interrupted)
        journal.do('unknown',{},send,lambda:{'observed':True})
        self.assertEqual(calls,['sent'])


if __name__=='__main__':unittest.main()
