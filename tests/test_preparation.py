"""Preparation cannot grant paid execution, reuse state or hide qualifications."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('prepare_project',ROOT/'scripts/prepare_hermes_project.py')
prepare_project=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare_project)


def project():
    return dict(version=1,namespace='delivery-kit-prepared-example',repository='https://github.com/example/product',
        branch='release/first',validation_image='sha256:'+'a'*64,browser_image='sha256:'+'b'*64,tests_dir='tests',
        qualification=False,technical_roles={'lead':'lead','cto':'cto'},coordination_roles={'product':'product','lead':'lead'},
        delivery_roles={'tests':'qa','integration':'devops'},reviewers={'backend':['lead','cto'],'lead':'cto','qa':'lead','devops':'qa'})


class PausedPreparation(unittest.TestCase):
    def test_policy_is_disabled_and_no_credentials_or_mutation_are_required_to_plan(self):
        parsed,policy,profiles=prepare_project.configuration(project(),'example/model',19390,10000)
        self.assertFalse(policy.enabled);self.assertEqual(policy.max_calls,10000)
        self.assertEqual(policy.project,parsed.fingerprint())
        self.assertEqual(profiles,['backend','cto','devops','lead','product','qa'])
        self.assertTrue(all(name not in policy.values() for name in ('api_key','provider_key','gh_token')))

    def test_invalid_project_or_model_is_rejected_before_touching_upstream(self):
        for changes in ({'branch':'main'},{'qualification':True},{'technical_roles':None}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                prepare_project.configuration({**project(),**changes},'example/model',19390,10000)
        for port in (True,80,65536):
            with self.assertRaises(ValueError):prepare_project.configuration(project(),'example/model',port,10000)
        with self.assertRaises(ValueError):prepare_project.configuration(project(),'missing-provider',19390,10000)

    def test_existing_installation_is_never_overwritten_or_resumed(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(prepare_project,'bind') as bind:
            root=Path(temporary);marker=root/'private-state';marker.write_text('preserve')
            with self.assertRaises(ValueError):prepare_project.prepare(root,root,project(),'example/model',19390,10000)
            self.assertEqual(marker.read_text(),'preserve');bind.assert_not_called()

    def test_private_state_cannot_be_prepared_in_an_unignored_public_source_path(self):
        with patch.object(prepare_project,'bind') as bind,patch.object(prepare_project.subprocess,'run') as git:
            git.return_value.returncode=1
            with self.assertRaisesRegex(ValueError,'Git-ignored'):
                prepare_project.prepare(ROOT/'not-an-installation',ROOT,project(),'example/model',19390,10000)
            bind.assert_not_called();self.assertFalse((ROOT/'not-an-installation').exists())


if __name__=='__main__':unittest.main()
