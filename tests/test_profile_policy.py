"""Profile admission cannot silently inherit another model, route or tool policy."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.effects import write_json
from fabriquinha.profile_policy import configuration,contract,inspect_profile,required,report,admission
from fabriquinha.config import Project
from test_delivery_core import configuration as project_configuration


def effective():
    value=configuration()
    value['auxiliary']['compression']=dict(provider='auto',model='',base_url='',api_key='',extra_body={})
    value['fallback_providers']=[];value['providers']={}
    value['context']={'engine':'compressor'}
    return value


class ProfilePolicy(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.project=Project.parse(project_configuration())
        self.home=self.root/'home/profiles/backend';self.home.mkdir(parents=True)
        write_json(self.home/'config.yaml',configuration())
        write_json(self.root/'installation.json',dict(project=self.project.fingerprint(),profile_contract=contract()))

    def test_old_small_window_requires_explicit_profile_migration(self):
        old=configuration();old['model']['context_length']=65536
        write_json(self.home/'config.yaml',old)
        result=inspect_profile(self.root,'backend',loader=lambda home:old)
        self.assertFalse(result['ready'])

    def test_configuration_is_independent_and_inspection_never_exposes_config(self):
        first=configuration();first['terminal']['backend']='local'
        self.assertEqual(configuration()['terminal']['backend'],'fabriquinha')
        loader=Mock(return_value=effective())
        result=inspect_profile(self.root,'backend',loader=loader)
        self.assertTrue(result['ready']);self.assertTrue(result['effective_checked'])
        self.assertEqual(result['errors'],[]);loader.assert_called_once_with(self.home)
        self.assertNotIn('base_url',json.dumps(result));self.assertNotIn('api_key',json.dumps(result))

    def test_bad_raw_or_unqualified_config_never_reaches_native_fallback(self):
        for content in ('{broken','{"model":1,"model":2}','['*2000+']'*2000,
                        json.dumps({**configuration(),'custom_providers':[{'api_key':'private-fixture'}]})):
            with self.subTest(content=content):
                (self.home/'config.yaml').write_text(content)
                loader=Mock(return_value=effective());result=inspect_profile(self.root,'backend',loader=loader)
                self.assertFalse(result['ready']);loader.assert_not_called()
                self.assertNotIn('private-fixture',json.dumps(result))

    def test_effective_overlay_is_checked_without_modifying_native_cache(self):
        changes=(('model',{'default':'other/model'}),('model',{'default':'auto'}),('model',{'api_mode':'other'}),
            ('memory',{'provider':'external'}),('fallback_providers',[{'provider':'other'}]),
            ('auxiliary',{'compression':{'base_url':'https://outside.invalid','api_key':'private-fixture'}}),
            ('tools',{'tool_search':{'enabled':'auto'}}),('terminal',{'backend':'local'}),
            ('context',{'engine':'other'}),('plugins',{'enabled':['unqualified']}),('hooks',{'pre_llm_call':[{}]}))
        for section,fields in changes:
            value=effective()
            if isinstance(fields,dict):value.setdefault(section,{}).update(fields)
            else:value[section]=fields
            original=copy.deepcopy(value)
            with self.subTest(section=section):
                result=inspect_profile(self.root,'backend',loader=lambda home:value)
                self.assertFalse(result['ready']);self.assertEqual(value,original)
                self.assertNotIn('outside.invalid',json.dumps(result));self.assertNotIn('private-fixture',json.dumps(result))

    def test_credential_stores_and_nonempty_env_are_unqualified_not_read_or_logged(self):
        loader=Mock(return_value=effective());auth=self.home/'auth.json';auth.write_text('private fixture')
        self.assertFalse(inspect_profile(self.root,'backend',loader=loader)['ready']);loader.assert_not_called()
        auth.unlink();env=self.home/'.env';env.write_text('# comment\n\n');env.chmod(0o600)
        self.assertTrue(inspect_profile(self.root,'backend',loader=loader)['ready'])
        env.write_text('OPENROUTER_API_KEY=private-fixture\n')
        result=inspect_profile(self.root,'backend',loader=loader)
        self.assertIn('ProfileCredentialsUnqualified',result['errors']);self.assertNotIn('private-fixture',json.dumps(result))

    def test_missing_symlink_and_unsafe_config_are_visible_without_reusing_another_home(self):
        loader=Mock(return_value=effective())
        self.assertIn('ProfileMissing',inspect_profile(self.root,'absent',loader=loader)['errors'])
        (self.home/'config.yaml').chmod(0o644)
        self.assertIn('ProfileConfigUnsafe',inspect_profile(self.root,'backend',loader=loader)['errors'])
        (self.home/'config.yaml').unlink();(self.home/'config.yaml').symlink_to(self.root/'installation.json')
        self.assertFalse(inspect_profile(self.root,'backend',loader=loader)['ready']);loader.assert_not_called()
        for name in ('../other','default','/tmp'):
            with self.assertRaises(ValueError):inspect_profile(self.root,name,loader=loader)

    def test_missing_legacy_pin_is_not_promoted_and_one_bad_profile_does_not_hide_others(self):
        self.assertTrue(required(self.project,self.root))
        results={'backend':{'ready':True,'errors':[]},'lead':{'ready':False,'errors':['ProfileConfigDrift']}}
        with patch('fabriquinha.profile_policy.inspect_profile',side_effect=lambda root,name:results.get(name,{'ready':False,'errors':['ProfileMissing']})):
            value=report(self.project,self.root)
        self.assertEqual(value['errors'],[])
        self.assertTrue(value['profiles']['backend']['ready']);self.assertFalse(value['profiles']['lead']['ready'])
        (self.root/'installation.json').unlink()
        self.assertFalse(required(self.project,self.root))  # Unpinned fixture remains an explicit fixture.
        from dataclasses import replace
        real=replace(self.project,qualification=False)
        self.assertTrue(required(real,self.root))
        self.assertEqual(report(real,self.root)['errors'],['ProfileContractRequired'])
        self.assertFalse(admission(real,self.root,'backend')['ready'])

    def test_missing_sdk_is_a_visible_refusal_not_a_config_fallback(self):
        value=inspect_profile(self.root,'backend',loader=Mock(side_effect=ImportError('SDK missing')))
        self.assertEqual(value['errors'],['ProfileSDKUnavailable']);self.assertFalse(value['effective_checked'])

    def test_pin_is_required_on_every_real_admission_not_only_at_start(self):
        from dataclasses import replace
        real=replace(self.project,qualification=False)
        pin=dict(project=real.fingerprint(),profile_contract=contract())
        write_json(self.root/'installation.json',pin)
        with patch('fabriquinha.profile_policy.inspect_profile',return_value={'ready':True,'errors':[]}):
            self.assertTrue(admission(real,self.root,'backend')['ready'])
            write_json(self.root/'installation.json',{**pin,'profile_contract':'changed'})
            self.assertEqual(admission(real,self.root,'backend')['errors'],['ProfileContractRequired'])


if __name__=='__main__':unittest.main()
