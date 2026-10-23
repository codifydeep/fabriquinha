"""Qualification orchestration safety, not evidence of a native agent run."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import qualify_quality_author_launch as qualification


class LaunchQualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.archive=Path(self.tmp.name);self.owner='delivery-kit-test-quality-launch-fixture';self.namespace='delivery-kit-test'
        self.ident='a'*64
        self.info=dict(Id=self.ident,Name='/delivery-kit-test-fixture',Image='sha256:'+'b'*64,Mounts=[],
            State=dict(Running=False,Status='exited'),Config=dict(Labels={'delivery-kit.owner':self.owner,
                'com.docker.compose.project':self.namespace+'-tests'}))
        self.result=SimpleNamespace(returncode=0,stdout='',stderr='')

    def inspect(self,args,**kwargs):
        if args[1]=='ps':
            self.assertIn('--no-trunc',args);return self.ident+'\n'
        return json.dumps([self.info])

    def test_retirement_uses_full_ids_archives_evidence_and_never_forces_or_deletes_volumes(self):
        with patch.object(qualification.subprocess,'check_output',side_effect=self.inspect),\
                patch.object(qualification,'command',return_value=self.result) as command,\
                patch.object(qualification,'await_retirement') as retired:
            count=qualification.observe_retirement(self.archive,self.owner,self.namespace)
        self.assertEqual(count,1);retired.assert_called_once_with('delivery-kit-test-fixture')
        self.assertTrue((self.archive/(self.ident+'-metadata.json')).exists())
        self.assertTrue((self.archive/(self.ident+'-logs.json')).exists())
        self.assertIn(['docker','rm',self.ident],[c.args[0] for c in command.call_args_list])
        for call in command.call_args_list:
            self.assertNotIn('--force',call.args[0]);self.assertNotIn('volume',call.args[0])

    def test_unknown_remove_ack_is_never_reposted(self):
        (self.archive/(self.ident+'-remove-intent.json')).write_text('{}')
        with patch.object(qualification.subprocess,'check_output',side_effect=self.inspect),\
                patch.object(qualification,'command',return_value=self.result) as command:
            with self.assertRaisesRegex(ValueError,'never repeat'):
                qualification.observe_retirement(self.archive,self.owner,self.namespace)
        self.assertFalse(any(c.args[0][1]=='rm' for c in command.call_args_list))

    def test_failed_retirement_never_stops_a_still_running_helper(self):
        self.info['State'].update(Running=True,Status='running')
        with patch.object(qualification.subprocess,'check_output',side_effect=self.inspect),\
                patch.object(qualification,'command',return_value=self.result) as command:
            with self.assertRaisesRegex(ValueError,'active helper'):
                qualification.observe_retirement(self.archive,self.owner,self.namespace,require_stopped=True)
        self.assertFalse(any(c.args[0][1] in ('stop','rm') for c in command.call_args_list))

    def test_adapter_fixture_does_not_inherit_installed_team_coordination_flags(self):
        import ast
        tree=ast.parse((Path(__file__).parent/'quality_launch_docker_probe.py').read_bytes())
        values={}
        for node in tree.body:
            if isinstance(node,ast.Assign):
                for target in node.targets:
                    if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='b':
                        values[target.attr]=ast.unparse(node.value)
        for name in ('QUALITY_TEAM_ENABLED','QUALITY_EXCLUSIVE_ENABLED','QUALITY_IMPLEMENTATION_ENABLED'):
            self.assertEqual(values[name],'False')

    def test_unknown_stop_ack_is_observed_without_another_stop_or_removal(self):
        self.info['State'].update(Running=True,Status='running')
        (self.archive/(self.ident+'-stop-intent.json')).write_text('{}')
        with patch.object(qualification.subprocess,'check_output',side_effect=self.inspect),\
                patch.object(qualification,'command',return_value=self.result) as command:
            with self.assertRaisesRegex(ValueError,'never repeat'):
                qualification.observe_retirement(self.archive,self.owner,self.namespace)
        self.assertFalse(any(c.args[0][1] in ('stop','rm') for c in command.call_args_list))

    def test_foreign_ownership_is_rejected_before_any_mutation(self):
        self.info['Config']['Labels']['delivery-kit.owner']='toso-foreign'
        with patch.object(qualification.subprocess,'check_output',side_effect=self.inspect),\
                patch.object(qualification,'command') as command:
            with self.assertRaisesRegex(ValueError,'ownership drift'):
                qualification.observe_retirement(self.archive,self.owner,self.namespace)
        command.assert_not_called()

    def test_completed_protocol_proof_requires_both_actual_frames_and_no_model_prompt(self):
        report=dict(status='passed',docker='real',acp='real',native_api='synthetic_fixture',delivery_approval=False,
            model_calls=0,prompts_sent=0,frames=[dict(method=m,status='passed',response_sha256='c'*64) for m in ('initialize','session/new')])
        qualification.validate_report(report)
        for key,value in [('model_calls',1),('prompts_sent',1),('native_api','real'),('frames',[]),('model_calls',False)]:
            bad=copy.deepcopy(report);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualification.validate_report(bad)


    def test_readonly_review_qualification_is_not_a_test_approval(self):
        source='80000000-0000-4000-8000-000000000001'
        frames=[dict(method=m,status='passed',response_sha256='c'*64) for m in ('initialize','session/new')]
        report=dict(status='passed',docker='real',acp='real',native_api='synthetic_fixture',delivery_approval=False,
            model_calls=0,prompts_sent=0,frames=frames,task_id=source,
            request_id='80000000-0000-4000-8000-000000000002',
            review_launch=dict(status='passed',source_task=source,snapshot_mount='readonly',manifest_sha256='d'*64,
                task_id='80000000-0000-4000-8000-000000000003',
                request_id='80000000-0000-4000-8000-000000000004',frames=frames,
                tests_approved=False,delivery_approval=False))
        qualification.validate_report(report)
        for key,value in [('snapshot_mount','readwrite'),('tests_approved',True),('frames',[]),('task_id',source)]:
            bad=copy.deepcopy(report);bad['review_launch'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualification.validate_report(bad)


if __name__=='__main__':unittest.main()
