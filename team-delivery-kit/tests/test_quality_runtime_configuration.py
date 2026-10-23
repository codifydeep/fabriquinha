"""Closed runtime-selector preflight; configuring it grants no execution."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import quality_runtime_configuration as runtime
import install_quality_preview as installer
import test_install_quality_preview as install_fixtures


class RuntimeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.value={key:'sha256:'+str(n)*64 for n,key in enumerate(runtime.IMAGES,1)}
        self.value.update(BROKER_QUALITY_TECHLEAD='10000000-0000-4000-8000-000000000001',
            BROKER_QUALITY_CTO='10000000-0000-4000-8000-000000000002')
        self.agents={self.value[key]:'planning' for key in runtime.ROLES}
        self.metadata={}
        for key,(component,entry) in runtime.IMAGES.items():
            labels={'delivery-kit.component':component,
                'delivery-kit.quality-phases':'tests_only_v2,test_review_v2,implementation_v2',
                'delivery-kit.quality-operations':'snapshot_after_implementation_v2,observe_green_v2,observe_reversion_v2'}
            self.metadata[self.value[key]]=dict(Id=self.value[key],Config=dict(User='10000:10000',
                Entrypoint=entry,Labels=labels,Env=[]))

    def test_exact_validated_selectors_do_not_contain_flags_models_or_authority(self):
        self.assertEqual(runtime.validate(self.value,self.metadata,self.agents),self.value)
        self.assertEqual(set(self.value),set(runtime.IMAGES)|runtime.ROLES)
        for key in ('BROKER_QUALITY_V2_ENABLED','BROKER_WORKER_IMAGE','MODEL_PROXY_MODEL','mounts','command'):
            with self.subTest(key=key),self.assertRaises(ValueError):runtime.syntax({**self.value,key:'anything'})

    def test_mutable_image_tags_missing_selectors_and_same_technical_roles_are_rejected(self):
        for change in ('tag','missing','same_role','bad_uuid'):
            value=copy.deepcopy(self.value)
            if change=='tag':value['BROKER_QUALITY_WORKER_IMAGE']='delivery-kit-worker:latest'
            elif change=='missing':value.pop('BROKER_QUALITY_COPY_IMAGE')
            elif change=='same_role':value['BROKER_QUALITY_CTO']=value['BROKER_QUALITY_TECHLEAD']
            else:value['BROKER_QUALITY_CTO']='not-an-agent'
            with self.subTest(change=change),self.assertRaises(ValueError):runtime.syntax(value)

    def test_runtime_metadata_cannot_supply_root_volumes_credentials_wrong_tools_or_operations(self):
        for change in ('root','volume','credentials','entrypoint','component','phases','operations','identity'):
            images=copy.deepcopy(self.metadata);key='BROKER_QUALITY_WORKER_IMAGE'
            if change=='operations':key='BROKER_QUALITY_GREEN_JOB_IMAGE'
            image=images[self.value[key]];config=image['Config']
            if change=='root':config['User']='0:0'
            elif change=='volume':config['Volumes']={'/workspace':{}}
            elif change=='credentials':config['Env']=['OPENROUTER_API_KEY=synthetic']
            elif change=='entrypoint':config['Entrypoint']=['sh']
            elif change=='component':config['Labels']['delivery-kit.component']='other'
            elif change=='phases':config['Labels']['delivery-kit.quality-phases']='tests_only_v2'
            elif change=='operations':config['Labels']['delivery-kit.quality-operations']='observe_green_v2'
            else:image['Id']='sha256:'+'f'*64
            with self.subTest(change=change),self.assertRaises(ValueError):runtime.validate(self.value,images,self.agents)

    def test_technical_escalation_roles_must_exist_with_planning_authority(self):
        for mode in ('review','implementation',None):
            agents=copy.deepcopy(self.agents);agents[self.value['BROKER_QUALITY_CTO']]=mode
            with self.subTest(mode=mode),self.assertRaises(ValueError):runtime.validate(self.value,self.metadata,agents)

    def test_probe_reads_only_pinned_controller_and_local_images(self):
        authority=SimpleNamespace(identity='a'*64,about=Mock(return_value=dict(maintenance=True,
            v2_enabled=False,implementation_enabled=False)),inspect_controller=Mock(return_value='a'*64))
        records=[json.dumps(dict(namespace='delivery-kit-test',agents=self.agents)),json.dumps(list(self.metadata.values()))]
        with patch.object(runtime,'Authority',return_value=authority),\
                patch.object(runtime.subprocess,'check_output',side_effect=records) as call:
            self.assertEqual(runtime.probe('delivery-kit-test','sha256:'+'f'*64,self.value),self.value)
        commands=[args.args[0] for args in call.call_args_list]
        self.assertEqual(commands[0],['docker','exec','a'*64,'python','-c',runtime.PROGRAM])
        self.assertEqual(commands[1][:3],['docker','image','inspect'])

    def test_live_or_unsealed_controller_blocks_before_configuration_reads(self):
        for about in (dict(maintenance=False,v2_enabled=False,implementation_enabled=False),
                dict(maintenance=True,v2_enabled=True,implementation_enabled=False)):
            with patch.object(runtime,'Authority',return_value=SimpleNamespace(about=lambda:about)),\
                    patch.object(runtime.subprocess,'check_output') as read:
                with self.assertRaises(ValueError):runtime.probe('delivery-kit-test','sha256:'+'f'*64,self.value)
            read.assert_not_called()

    def test_upgrade_preflight_accepts_only_sealed_idle_exclusive_uniform_flags(self):
        authority=SimpleNamespace(identity='a'*64,about=Mock(return_value=dict(maintenance=True,
            v2_enabled=True,implementation_enabled=True)),inspect_controller=Mock(return_value='a'*64))
        native=dict(namespace='delivery-kit-test',agents=self.agents,flags=[True]*4,exclusive=True)
        with patch.object(runtime,'Authority',return_value=authority),\
                patch('qualify_quality_red_observer.require_idle') as idle,\
                patch.object(runtime.subprocess,'check_output',side_effect=[json.dumps(native),json.dumps(list(self.metadata.values()))]):
            self.assertEqual(runtime.probe('delivery-kit-test','sha256:'+'f'*64,self.value,sealed_upgrade=True),self.value)
            idle.assert_called_once_with('delivery-kit-test')
        for change in (dict(flags=[True,False,True,True]),dict(exclusive=False),dict(flags=[1]*4)):
            with patch.object(runtime,'Authority',return_value=authority),patch('qualify_quality_red_observer.require_idle'),\
                    patch.object(runtime.subprocess,'check_output',return_value=json.dumps({**native,**change})),\
                    self.assertRaises(ValueError):runtime.probe('delivery-kit-test','sha256:'+'f'*64,self.value,sealed_upgrade=True)
        with patch.object(runtime,'Authority',return_value=authority),\
                patch('qualify_quality_red_observer.require_idle',side_effect=ValueError('active native work')),\
                patch.object(runtime.subprocess,'check_output') as read,self.assertRaises(ValueError):
            runtime.probe('delivery-kit-test','sha256:'+'f'*64,self.value,sealed_upgrade=True)
        read.assert_not_called()

    def test_installer_accepts_only_explicit_complete_selectors_with_all_flags_off(self):
        fixture=install_fixtures.PreviewInstallTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        after=fixture.after();after['Config']['Env'] += [k+'='+v for k,v in self.value.items()]
        installer.verify_preservation(fixture.before,after,after['Image'],runtime=self.value)
        with self.assertRaises(ValueError):installer.verify_preservation(fixture.before,after,after['Image'])
        for change in ('flag','credential','selector'):
            bad=copy.deepcopy(after)
            if change=='flag':bad['Config']['Env']=[v.replace('BROKER_QUALITY_V2_ENABLED=0','BROKER_QUALITY_V2_ENABLED=1') for v in bad['Config']['Env']]
            elif change=='credential':bad['Config']['Env'][0]='PRIVATE=changed'
            else:bad['Config']['Env']=[v for v in bad['Config']['Env'] if not v.startswith('BROKER_QUALITY_COPY_IMAGE=')]
            with self.subTest(change=change),self.assertRaises(ValueError):
                installer.verify_preservation(fixture.before,bad,bad['Image'],runtime=self.value)

    def test_private_configuration_rejects_public_permissions_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary).resolve()/'config.json';path.write_text(json.dumps(self.value));path.chmod(0o600)
            self.assertEqual(runtime.load(path),self.value)
            path.chmod(0o644)
            with self.assertRaises(ValueError):runtime.load(path)
            path.chmod(0o600);path.write_text('{"same":1,"same":2}')
            with self.assertRaises(ValueError):runtime.load(path)

    def test_installation_identity_cannot_be_reused_with_different_runtime_selectors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();operation='10000000-0000-4000-8000-000000000003'
            image='sha256:'+'a'*64;private=root/'.local-test'/'backups'/('quality-preview-install-'+operation)
            private.mkdir(mode=0o700,parents=True)
            state=dict(namespace='delivery-kit-test',image=image,operation=operation,
                stage='installed_disabled',runtime=self.value,receipt={'configured':True})
            (private/'state.json').write_text(json.dumps(state))
            with patch.object(installer,'ROOT',root):
                self.assertEqual(installer.install('delivery-kit-test',image,operation,runtime=self.value),state['receipt'])
                with self.assertRaises(ValueError):installer.install('delivery-kit-test',image,operation)


if __name__=='__main__':unittest.main()
