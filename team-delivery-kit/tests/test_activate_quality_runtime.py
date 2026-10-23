"""Activation flag boundary and unknown effect recovery, not native delivery."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
import activate_quality_runtime as activation
import test_install_quality_preview as fixtures


class ActivationTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.PreviewInstallTests();f.setUp();self.addCleanup(f.doCleanups)
        self.before=f.after();self.before['Id']='a'*64
        self.before['Image']='sha256:'+'b'*64
        self.after=copy.deepcopy(self.before);self.after['Id']='c'*64
        self.after['Config']['Env']=[v for v in self.after['Config']['Env'] if v.split('=',1)[0] not in activation.FLAGS]
        self.after['Config']['Env'] += [k+'=1' for k in activation.FLAGS]

    def test_only_five_flags_change_and_mounts_credentials_helpers_stay_exact(self):
        activation.verify(self.before,self.after)
        for kind in ('image','volume','secret','helper','missing_flag','resource','owner'):
            changed=copy.deepcopy(self.after)
            if kind=='image':changed['Image']='sha256:'+'d'*64
            elif kind=='volume':changed['Mounts'][0]['Name']='foreign'
            elif kind=='secret':changed['Config']['Env'][0]='PRIVATE=changed'
            elif kind=='helper':changed['Config']['Env'].append('BROKER_QUALITY_WORKER_IMAGE=changed')
            elif kind=='missing_flag':changed['Config']['Env'].pop()
            elif kind=='owner':changed['Config']['Labels']['com.docker.compose.project']='toso-unrelated'
            else:changed['HostConfig']['Memory']=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):activation.verify(self.before,changed)

    def prepare(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name).resolve()
        root.chmod(0o700);private=root/'.local-test';private.mkdir(mode=0o700)
        backups=private/'backups';backups.mkdir(mode=0o700)
        self.op='10000000-0000-4000-8000-000000000001';self.inst='10000000-0000-4000-8000-000000000002'
        self.pin='e'*64;self.ns='delivery-kit-test';self.image=self.before['Image'];self.maintenance='10000000-0000-4000-8000-000000000003'
        self.archive=backups/('quality-activation-'+self.op);self.archive.mkdir(mode=0o700)
        state=dict(identity=dict(namespace=self.ns,image=self.image,payload_pin=self.pin,operation=self.op,install_operation=self.inst),
            stage='prepared',previous_id=self.before['Id'],argv=['docker','compose'],deadline=9999999999)
        activation.install.save(self.archive/'state.json',state)
        activation.install.save(self.archive/'before.json',self.before)
        activation.install.save(self.archive/'others.json',[])
        payload=dict(maintenance_operation=self.maintenance,plan=dict(issue_id='issue'))
        mocks=[patch.object(activation,'ROOT',root),patch.object(activation.enrollment,'load',return_value=payload),
            patch.object(activation,'preflight',return_value=self.before['Id']),
            patch.object(activation,'require_idle',return_value=(dict(operation_id=self.maintenance),{})),
            patch.object(activation,'Service',return_value=SimpleNamespace(stopped=Mock())),
            patch.object(activation,'Authority',return_value=SimpleNamespace(about=lambda:dict(v2_enabled=True,implementation_enabled=True,maintenance=True)))]
        for mock in mocks:mock.start();self.addCleanup(mock.stop)

    def run_activation(self):return activation.activate(self.ns,self.image,'/private/payload.json',self.pin,self.op,self.inst)

    def test_unknown_compose_ack_is_not_sent_twice(self):
        import subprocess
        self.prepare()
        with patch.object(activation.install,'command',side_effect=subprocess.TimeoutExpired('compose',45)) as command,\
                patch.object(activation.install,'inspect',return_value=self.before):
            for _ in range(2):
                with self.assertRaises(activation.Pending):self.run_activation()
        self.assertEqual(command.call_count,1)

    def test_success_remains_sealed_and_does_not_start_models_or_assign_issue(self):
        self.prepare()
        with patch.object(activation.install,'command') as command,patch.object(activation.install,'inspect',return_value=self.after):
            result=self.run_activation();self.assertEqual(self.run_activation(),result)
        self.assertEqual(command.call_count,1);self.assertEqual(result['stage'],'activated_sealed')
        self.assertFalse(result['maintenance_released']);self.assertEqual(result['model_calls'],0)

    def test_expired_observation_keeps_visible_block_without_retry(self):
        self.prepare()
        with patch.object(activation.install,'command') as command,patch.object(activation.install,'inspect',return_value=self.before),\
                patch.object(activation.time,'time',return_value=10000000000):
            result=self.run_activation();self.assertEqual(self.run_activation(),result)
        self.assertEqual(command.call_count,1);self.assertEqual(result['stage'],'technical_blocked')


if __name__=='__main__':unittest.main()
