"""Scoped native acceptance gets an explicit account, never ambient fallback."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.github_auth import configure,env_allowed,report,metadata,profiles
from fabriquinha.operations import Control
from fabriquinha.profile_policy import configuration,inspect_profile
from test_preparation import project


class GitHubIdentity(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve();self.root=self.base/'installation';self.root.mkdir()
        self.config=self.base/'controller-gh';self.config.mkdir()
        (self.config/'hosts.yml').write_text('private fixture; must never be read or copied')
        self.project=Project.parse({**project(),'local_ci':dict(context='fabriquinha-local-ci',publisher='fixture')})
        write_json(self.root/'project.json',{**project(),'local_ci':dict(context='fabriquinha-local-ci',publisher='fixture')})
        for name in profiles(self.project)+['backend']:
            home=self.root/'home/profiles'/name;home.mkdir(parents=True,exist_ok=True)
            write_json(home/'config.yaml',configuration());(home/'.env').write_text('# empty profile\n');(home/'.env').chmod(0o600)
        control=Control(self.root,self.project);control.pause()
        self.runtime=SimpleNamespace(root=self.root,project=self.project,control=control,
            status=lambda:dict(control=dict(drained=True)))
        self.calls=[]
        def query(args,**kwargs):
            self.calls.append((args,kwargs['env']))
            return SimpleNamespace(stdout=b'{"login":"fixture"}')
        self.query=patch('fabriquinha.github_auth.subprocess.run',side_effect=query)
        self.query.start();self.addCleanup(self.query.stop)

    def test_explicit_identity_is_metadata_only_scoped_and_idempotent(self):
        self.assertFalse(report(self.project,self.root)['ready'])
        with patch.dict(os.environ,{'GH_TOKEN':'ambient-secret','GITHUB_TOKEN':'another-secret'}):
            result=configure(self.runtime,self.config)
        self.assertTrue(result['ready']);self.assertFalse(result['tokens_copied'])
        self.assertEqual(result['github_mutations'],0)
        args,env=self.calls[0]
        self.assertEqual(args,['gh','api','--hostname','github.com','user'])
        self.assertEqual(env['GH_CONFIG_DIR'],str(self.config));self.assertNotIn('GH_TOKEN',env);self.assertNotIn('GITHUB_TOKEN',env)
        value=json.loads((self.root/'github-auth.json').read_bytes())
        for name in profiles(self.project):
            path=self.root/'home/profiles'/name/'.env'
            self.assertEqual(path.read_text(),metadata(value));self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertTrue(inspect_profile(self.root,name,loader=lambda home:configuration())['ready'])
        self.assertEqual((self.root/'home/profiles/backend/.env').read_text(),'# empty profile\n')
        self.assertFalse(any(path.name=='hosts.yml' for path in self.root.rglob('*')))
        self.assertNotIn('private fixture',json.dumps(value));self.assertEqual(configure(self.runtime,self.config),result)

    def test_no_active_workers_or_unpaused_provisioning(self):
        self.runtime.status=lambda:dict(control=dict(drained=False))
        with self.assertRaisesRegex(ValueError,'drained'):configure(self.runtime,self.config)
        self.assertFalse(self.calls)
        self.runtime.status=lambda:dict(control=dict(drained=True))
        with self.runtime.control.lock():self.runtime.control.resume(self.runtime.control.read()['episode'])
        with self.assertRaisesRegex(ValueError,'paused'):configure(self.runtime,self.config)
        self.assertFalse(self.calls)

    def test_account_mismatch_preserves_every_file_and_never_uses_ambient_credentials(self):
        with patch('fabriquinha.github_auth.subprocess.run',return_value=SimpleNamespace(stdout=b'{"login":"wrong"}')):
            with self.assertRaisesRegex(ValueError,'publisher'):configure(self.runtime,self.config)
        self.assertFalse((self.root/'github-auth.json').exists())
        self.assertTrue(all((self.root/'home/profiles'/n/'.env').read_text()=='# empty profile\n' for n in profiles(self.project)))

    def test_credential_or_unknown_env_is_not_overwritten(self):
        home=self.root/'home/profiles'/profiles(self.project)[0];env=home/'.env'
        env.write_text('GITHUB_TOKEN=private-fixture\n')
        with self.assertRaisesRegex(ValueError,'overwrite'):configure(self.runtime,self.config)
        self.assertEqual(env.read_text(),'GITHUB_TOKEN=private-fixture\n');self.assertFalse(self.calls)
        self.assertFalse(inspect_profile(self.root,home.name,loader=lambda home:configuration())['ready'])

    def test_drift_and_other_profiles_never_gain_a_pointer(self):
        configure(self.runtime,self.config);value=json.loads((self.root/'github-auth.json').read_bytes())
        text=metadata(value)
        self.assertFalse(env_allowed(self.root,'backend',text));self.assertFalse(env_allowed(self.root,None,text))
        self.assertFalse(env_allowed(self.root,profiles(self.project)[0],text+'OPENROUTER_API_KEY=private-fixture\n'))
        self.assertFalse(env_allowed(self.root,profiles(self.project)[0],text.replace('github.com','example.invalid')))
        env=self.root/'home/profiles'/profiles(self.project)[0]/'.env';env.write_text(text+'GH_TOKEN=private-fixture\n')
        self.assertFalse(report(self.project,self.root)['ready'])
        env.write_text(text);value['profiles'].append('backend');write_json(self.root/'github-auth.json',value)
        self.assertFalse(report(self.project,self.root)['ready']);self.assertFalse(env_allowed(self.root,'backend',text))

    def test_auth_directory_must_be_external_and_symlinks_or_rebinding_are_refused(self):
        inside=self.root/'credentials';inside.mkdir()
        with self.assertRaises(ValueError):configure(self.runtime,inside)
        link=self.base/'link';link.symlink_to(self.config,target_is_directory=True)
        with self.assertRaises(ValueError):configure(self.runtime,link)
        configure(self.runtime,self.config)
        other=self.base/'other';other.mkdir()
        with self.assertRaisesRegex(ValueError,'preserved'):configure(self.runtime,other)
        path=self.root/'github-auth.json';path.chmod(0o644)
        self.assertFalse(report(self.project,self.root)['ready'])

    def test_interruption_keeps_readiness_false_and_same_identity_can_finish(self):
        replace=os.replace
        def interrupted(source,destination):
            if Path(destination).name=='.env':raise OSError('fixture interruption')
            return replace(source,destination)
        with patch('fabriquinha.github_auth.os.replace',side_effect=interrupted):
            with self.assertRaises(OSError):configure(self.runtime,self.config)
        self.assertTrue((self.root/'github-auth.json').exists())
        self.assertFalse(report(self.project,self.root)['ready'])
        self.assertTrue(configure(self.runtime,self.config)['ready'])

    def test_dotenv_interpolation_and_control_characters_in_directory_are_refused(self):
        for name in ('${GH_CONFIG_DIR}','line\nbreak','back\\slash'):
            path=self.base/name;path.mkdir()
            with self.assertRaises(ValueError):configure(self.runtime,path)
        self.assertFalse(self.calls)


if __name__=='__main__':unittest.main()
