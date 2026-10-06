import unittest
import tempfile
import hashlib
from pathlib import Path
from unittest.mock import patch
import deploy_u3_coverage as probe


class CoverageDeploymentTests(unittest.TestCase):
    def test_probe_is_not_feature_tdd_or_release_approval(self):
        value=probe.initial({'merged_sha':'a'*40,'final_review_sha256':'b'*64})
        self.assertEqual(value['source_sha'],'a'*40)
        for key in ('historical_tdd_red','product_admission_authorized','release_homologated'):
            self.assertIs(value[key],False)

    def test_exact_safe_container_identity_required_before_stop_or_restore(self):
        data=dict(Id='container',Image='sha256:'+'a'*64,
            Config=dict(Labels={'delivery-kit.u3-coverage':probe.OWNER,'delivery-kit.source-sha':'b'*40},User='10000:10000'),
            HostConfig=dict(Privileged=False,ReadonlyRootfs=True,Mounts=[],Binds=[],NetworkMode='bridge',
                CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                PortBindings={'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':str(probe.PORT)}]}))
        probe.identity(data,'sha256:'+'a'*64,'b'*40)
        for field,value in (('Privileged',True),('ReadonlyRootfs',False),
                            ('Binds',['/var/run/docker.sock:/var/run/docker.sock']),('PortBindings',{}),
                            ('NetworkMode','host'),('PidMode','host'),('Devices',[{'PathOnHost':'/dev/mem'}])):
            with self.assertRaises(ValueError):probe.identity(dict(data,HostConfig=dict(data['HostConfig'],**{field:value})),data['Image'],'b'*40)
        with self.assertRaises(ValueError):probe.identity(data,'sha256:'+'c'*64,'b'*40)

    def test_restarts_do_not_blindly_repeat_failed_or_incomplete_qualification(self):
        for stage in ('deployment_intent','browser_intent','rollback_intent','blocked'):
            self.assertFalse(probe.can_begin({'stage':stage}))
        self.assertTrue(probe.can_begin(None))

    def test_cleanup_recovery_rejects_functional_failure_and_other_owners(self):
        for value in ({'status':'failed','cleanup':'failed','result':{'status':'failed'}},
                      {'status':'failed','cleanup':'failed','result':{'status':'passed'},'owner':'unrelated'}):
            with self.assertRaises(ValueError):probe.cleanup_evidence(value,{},Path('/tmp/no-proof.json'))

    def test_cleanup_timeout_is_resolved_by_observation_not_duplicate_mutation(self):
        import subprocess
        data={'Id':'owned-id','Config':{'Labels':{'delivery-kit.browser-qa':'owner'}},'State':{'Running':False}}
        with patch.object(probe,'inspect',side_effect=[data,None]), patch.object(probe,'docker',side_effect=subprocess.TimeoutExpired('docker',30)) as mutation:
            probe.remove_owned('container','name','owner')
        self.assertEqual(mutation.call_count,1)

    def test_cleanup_ownership_mismatch_never_mutates(self):
        with patch.object(probe,'inspect',return_value={'Config':{'Labels':{}}}),patch.object(probe,'docker') as mutation:
            with self.assertRaises(ValueError):probe.remove_owned('container','name','owner')
        mutation.assert_not_called()

    def test_recovery_binds_result_source_image_container_and_screenshot(self):
        owner='delivery-kit-browser-'+'a'*32
        receipt=dict(source_sha='b'*40,image='sha256:'+'c'*64,container_id='d'*64,browser_config={})
        proof=dict(status='failed',cleanup='failed',error=' cleanup: timeout',automated=True,owner=owner,
            resources=[['network',owner],['container',owner+'-app'],['container',owner+'-browser']],
            result={'status':'passed','source_sha':receipt['source_sha']},
            identity=dict(source_sha=receipt['source_sha'],application_image=receipt['image'],
                deployed_container_id=receipt['container_id'],config={},runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'},
                scenario_sha256=hashlib.sha256(probe.browser.SCRIPT.read_bytes()).hexdigest()),
            screenshot_sha256=hashlib.sha256(b'proof').hexdigest())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'receipt.json';path.with_suffix('.png').write_bytes(b'proof')
            self.assertEqual(probe.cleanup_evidence(proof,receipt,path),proof['resources'])
            for field in ('source_sha','image','container_id'):
                with self.assertRaises(ValueError):probe.cleanup_evidence(proof,dict(receipt,**{field:'wrong'}),path)
            path.with_suffix('.png').write_bytes(b'changed')
            with self.assertRaises(ValueError):probe.cleanup_evidence(proof,receipt,path)
