"""Only capacity/source may change; credentials, counters and limits may not."""
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import install_model_proxy_capacity as install


class InstallModelProxyCapacityTests(unittest.TestCase):
    def setUp(self):
        self.before=dict(Name='/delivery-kit-test-model-proxy-1',Image='sha256:'+'a'*64,
            State=dict(Running=False),Mounts=[dict(Name='meter',Destination='/meter',RW=True),
                dict(Name='secret',Destination='/secret',RW=False)],
            HostConfig=dict(ReadonlyRootfs=True,Memory=134217728,NetworkMode='original',Binds=['meter:/meter:rw']),
            Config=dict(User='10000:10000',Entrypoint=['python','/model_proxy.py'],Cmd=None,WorkingDir='/eval-state',
                Env=['MODEL_PROXY_MAX_CALLS=10000','MODEL_PROXY_COUNTER_PATH=/meter/calls.json'],
                Labels={'com.docker.compose.project':'delivery-kit-test','com.docker.compose.service':'model-proxy'}))
        self.after=copy.deepcopy(self.before);self.after['Image']='sha256:'+'b'*64;self.after['State']['Running']=True
        self.after['Config']['Env'].append('MODEL_PROXY_MAX_REQUEST_BYTES=2097152')

    def test_only_verified_image_and_request_capacity_change(self):
        install.verify_proxy(self.before,self.after,'sha256:'+'b'*64)
        stopped=copy.deepcopy(self.after);stopped['State']['Running']=False
        install.verify_proxy(self.before,stopped,'sha256:'+'b'*64,running=False)

    def test_call_ceiling_meter_key_mount_network_resources_and_commands_are_preserved(self):
        for field in ('ceiling','counter','secret','socket','memory','network','command','capacity'):
            value=copy.deepcopy(self.after)
            if field=='ceiling':value['Config']['Env'][0]='MODEL_PROXY_MAX_CALLS=99999'
            elif field=='counter':value['Config']['Env'][1]='MODEL_PROXY_COUNTER_PATH=/tmp/reset.json'
            elif field=='secret':value['Mounts'][1]['Name']='other-secret'
            elif field=='socket':value['Mounts'].append(dict(Destination='/var/run/docker.sock',RW=True))
            elif field=='memory':value['HostConfig']['Memory']*=2
            elif field=='network':value['HostConfig']['NetworkMode']='host'
            elif field=='command':value['Config']['Entrypoint']=['sh']
            else:value['Config']['Env'][-1]='MODEL_PROXY_MAX_REQUEST_BYTES=4194304'
            with self.subTest(field=field),self.assertRaises(ValueError):install.verify_proxy(self.before,value,'sha256:'+'b'*64)

    def test_counter_requires_exact_nonnegative_integer_and_retains_raw_digest(self):
        value=install.counter_receipt(b'{"calls":6207}')
        self.assertEqual(value['calls'],6207);self.assertEqual(len(value['sha256']),64)
        for raw in (b'{"calls":true}',b'{"calls":-1}',b'{"calls":1,"reset":true}',b'[]'):
            with self.assertRaises(ValueError):install.counter_receipt(raw)

    def test_duplicate_environment_and_foreign_service_fail_closed(self):
        value=copy.deepcopy(self.after);value['Config']['Env'].append('MODEL_PROXY_MAX_CALLS=10000')
        with self.assertRaises(ValueError):install.verify_proxy(self.before,value,'sha256:'+'b'*64)

    def test_live_kernel_lock_prevents_a_second_install_even_with_another_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            private=Path(directory)
            with install.installation_lock(private):
                with self.assertRaises(install.Pending):
                    with install.installation_lock(private):raise AssertionError('second installation entered')
            with install.installation_lock(private):pass

    def test_legacy_capacity_is_verified_from_archived_source_without_execution(self):
        self.assertEqual(install.old_capacity(b'MAX_BODY = 512 * 1024\n',{}),524288)
        for program,env in ((b'MAX_BODY=999999\n',{}),(b'MAX_BODY=run()\n',{}),
                (b'MAX_BODY=512*1024\n',{'MODEL_PROXY_MAX_REQUEST_BYTES':'2097152'})):
            with self.assertRaises(ValueError):install.old_capacity(program,env)

    def test_unknown_recreation_or_stop_only_observes_the_original_effect(self):
        for stage in ('recreate_intent','stop_intent'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();operation='a0000000-0000-4000-8000-000000000001'
                proof='a0000000-0000-4000-8000-000000000002';image='sha256:'+'b'*64
                archive=root/'.local-test/backups'/('model-proxy-install-'+operation)
                archive.mkdir(mode=0o700,parents=True);(root/'.local-test').chmod(0o700);archive.parent.chmod(0o700)
                before={**self.before,'Id':'c'*64}
                current=before if stage=='recreate_intent' else {**self.after,'Id':'e'*64}
                state=dict(namespace='delivery-kit-test',image=image,operation=operation,qualification_id=proof,
                    stage=stage,maintenance_operation='held',controller_id='d'*64,deadline=time.time()+300,new_container_id='e'*64)
                install.base.save(archive/'before.json',before);install.base.save(archive/'state.json',state)
                def inspect(name):return dict(Id='d'*64) if name.endswith('execution-broker-1') else current
                with patch.object(install,'ROOT',root),patch.object(install,'require_idle',return_value=(dict(operation_id='held'),{})), \
                        patch.object(install.base,'inspect',side_effect=inspect),patch.object(install.base,'command') as command:
                    with self.assertRaises(install.Pending):install.install('delivery-kit-test',image,operation,proof)
                command.assert_not_called()
        value=copy.deepcopy(self.after);value['Config']['Labels']['com.docker.compose.service']='other'
        with self.assertRaises(ValueError):install.verify_proxy(self.before,value,'sha256:'+'b'*64)


if __name__=='__main__':unittest.main()
