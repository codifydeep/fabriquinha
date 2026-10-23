"""Installation preflight and preservation invariants, not a deployed proof."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import install_quality_preview as install


class PreviewInstallTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.config=self.root/'compose.yaml';self.config.write_text('services: {}\n')
        self.env=self.root/'private.env';self.env.write_text('PRIVATE=not-published\n');self.env.chmod(0o600)
        self.before=dict(Name='/delivery-kit-test-execution-broker-1',Image='sha256:'+'a'*64,
            State=dict(Running=True),Mounts=[dict(Destination='/broker-state',Name='original-state')],
            HostConfig=dict(ReadonlyRootfs=True,Memory=268435456,NetworkMode='original-network'),
            Config=dict(User='0:0',Env=['PRIVATE=not-published','BROKER_WORKER_IMAGE=sha256:original'],
                Labels={'com.docker.compose.project':'delivery-kit-test','com.docker.compose.service':'execution-broker',
                    'com.docker.compose.project.config_files':str(self.config),
                    'com.docker.compose.project.environment_file':str(self.env),
                    'com.docker.compose.project.working_dir':str(self.root)}))

    def test_configuration_reuses_exact_private_env_and_source_files(self):
        with patch.object(install,'ROOT',self.root):argv,files=install.configuration(self.before,'delivery-kit-test')
        self.assertEqual(files,[self.config]);self.assertIn(str(self.env),argv)
        self.assertNotIn('not-published',' '.join(argv))

    def test_foreign_project_or_public_env_is_rejected(self):
        with patch.object(install,'ROOT',self.root):
            with self.assertRaises(ValueError):install.configuration(self.before,'delivery-kit-other')
            self.env.chmod(0o644)
            with self.assertRaises(ValueError):install.configuration(self.before,'delivery-kit-test')

    def after(self):
        value=copy.deepcopy(self.before);value['Image']='sha256:'+'b'*64
        value['Config']['Env'] += [key+'=0' for key in install.FLAGS]
        return value

    def test_only_image_and_explicit_disabled_flags_may_change(self):
        install.verify_preservation(self.before,self.after(),'sha256:'+'b'*64)

    def test_startup_interpolation_preserves_namespace_ports_worker_and_call_ceiling(self):
        before=copy.deepcopy(self.before);before['Config']['Env'][1]='BROKER_WORKER_IMAGE=sha256:'+'a'*64
        companions={}
        for service,port,host in (('backend','8080/tcp','19100'),('frontend','3000/tcp','19310'),('model-proxy',None,None)):
            companions[service]=dict(Config=dict(Labels={'com.docker.compose.project':'delivery-kit-test',
                'com.docker.compose.service':service},Env=['MODEL_PROXY_MAX_CALLS=10000']),
                HostConfig=dict(PortBindings={port:[dict(HostIp='127.0.0.1',HostPort=host)]} if port else {}))
        values=install.interpolation(before,'delivery-kit-test',companions)
        self.assertEqual(values['MODEL_PROXY_MAX_CALLS'],'10000');self.assertEqual(values['EVAL_FRONTEND_PORT'],'19310')
        self.assertEqual(values['BROKER_WORKER_IMAGE'],'sha256:'+'a'*64)
        self.assertEqual(values['DELIVERY_KIT_COMPOSE_PROJECT'],'delivery-kit-test')

    def test_state_volume_credentials_model_or_execution_activation_cannot_change(self):
        for mutation in ('volume','credential','worker','enabled','resource'):
            after=self.after()
            if mutation=='volume':after['Mounts'][0]['Name']='different-state'
            elif mutation=='credential':after['Config']['Env'][0]='PRIVATE=changed'
            elif mutation=='worker':after['Config']['Env'][1]='BROKER_WORKER_IMAGE=changed'
            elif mutation=='enabled':after['Config']['Env'][-1]=install.FLAGS[-1]+'=1'
            else:after['HostConfig']['Memory']=1073741824
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                install.verify_preservation(self.before,after,'sha256:'+'b'*64)

    def test_desktop_socket_alias_requires_same_daemon_and_exact_remaining_mounts(self):
        old=copy.deepcopy(self.before);new=self.after()
        old['Mounts'].append(dict(Destination='/var/run/docker.sock',Source='/run/host-services/docker.proxy.sock',
            Type='bind',RW=True,Mode='rw',Propagation='rprivate'))
        new['Mounts'].append({**old['Mounts'][-1],'Source':'/var/run/docker.sock'})
        old['HostConfig']['Binds']=['state:/broker-state:rw','/run/host-services/docker.proxy.sock:/var/run/docker.sock:rw']
        new['HostConfig']['Binds']=['/var/run/docker.sock:/var/run/docker.sock:rw','state:/broker-state:rw']
        with self.assertRaises(ValueError):install.verify_preservation(old,new,'sha256:'+'b'*64)
        self.assertTrue(install.verify_preservation(old,new,'sha256:'+'b'*64,socket_daemon_verified=True))
        new['Mounts'][-1]['Source']='/tmp/foreign.sock'
        with self.assertRaises(ValueError):install.verify_preservation(old,new,'sha256:'+'b'*64,socket_daemon_verified=True)

    def test_controller_logs_are_private_and_reused_before_retirement(self):
        before=dict(Id='a'*64)
        with patch.object(install,'command',return_value=SimpleNamespace(stdout='diagnostic',stderr='warning')) as read:
            install.archive_controller_logs(before,self.root);install.archive_controller_logs(before,self.root)
        read.assert_called_once();path=self.root/'previous-controller-logs.json'
        self.assertEqual(path.stat().st_mode&0o077,0)


if __name__=='__main__':unittest.main()
