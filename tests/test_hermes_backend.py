"""Controller-selected native-tool sandbox boundaries, without Hermes imports."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.hermes import Sandbox, command, sandbox_context, incomplete_activity, terminal_arguments
import fabriquinha.hermes as adapter
from fabriquinha.effects import Pending
from test_delivery_core import configuration


class NativeBackendPolicy(unittest.TestCase):
    def test_activity_address_is_inherited_without_changing_the_stored_route(self):
        route=dict(base_url='http://127.0.0.1:1234/v1',model='fixture',api_key='fixture-only',provider='custom',api_mode='chat_completions')
        before=dict(route)
        self.assertTrue(callable(getattr(adapter,'activity_route',None)))
        scoped=adapter.activity_route(route,'a'*64)
        self.assertEqual(scoped['base_url'],'http://127.0.0.1:1234/activities/'+'a'*64+'/v1')
        self.assertEqual(route,before);self.assertEqual(scoped['model'],route['model'])
        for url in ('http://127.0.0.1:1234/v1?scope=other','http://127.0.0.1:1234/v1#other','http://user:password@127.0.0.1:1234/v1','http://127.0.0.1:1234/other'):
            with self.subTest(url=url),self.assertRaises(ValueError):adapter.activity_route({**route,'base_url':url},'a'*64)
        with self.assertRaises(ValueError):adapter.activity_route(route,'not-an-activity')

    def test_exploration_cannot_request_a_terminal_batch_beyond_the_controller_limit(self):
        for timeout in (570,0,-1,True,'120',120.5):
            with self.subTest(timeout=timeout),self.assertRaises(ValueError):
                terminal_arguments({'command':'a long experiment','timeout':timeout},120)
        self.assertEqual(terminal_arguments({'command':'short experiment'},120)['timeout'],120)
        self.assertEqual(terminal_arguments({'command':'short experiment','timeout':10},120)['timeout'],10)

    def test_terminal_deadline_is_inside_container_even_if_docker_client_dies(self):
        from fabriquinha.hermes import bounded_exec, EXEC_GUARD
        args=bounded_exec('c'*64,['bash','-c','sleep 999'],5,stdin=True)
        self.assertEqual(args[:4],['docker','exec','-i','c'*64])
        self.assertEqual(args[4:9],['python','-B','-c',EXEC_GUARD,'5'])
        self.assertEqual(args[9:],['bash','-c','sleep 999'])
        self.assertEqual(bounded_exec('c'*64,['bash','-c','true'],300)[-4],'120')
        for value in (0,-1,True,float('nan'),float('inf')):
            with self.subTest(timeout=value),self.assertRaises(ValueError):bounded_exec('c'*64,['bash','-c','true'],value)

    def test_applied_diagnosis_refreshes_context_but_ordinary_resume_keeps_anchor(self):
        from dataclasses import replace
        from fabriquinha.hermes import activity_anchor
        route=dict(model='same-model',provider='custom',api_mode='chat_completions')
        original=activity_anchor(self.project,self.run,route)
        self.assertEqual(original,activity_anchor(self.project,replace(self.run,number=2),route))
        recovered=activity_anchor(self.project,self.run,route,'d'*64)
        self.assertNotEqual(original,recovered)
        self.assertEqual(recovered,activity_anchor(self.project,replace(self.run,number=3),route,'d'*64))
        self.assertNotEqual(recovered,activity_anchor(self.project,self.run,route,'e'*64))
        with self.assertRaises(ValueError):activity_anchor(self.project,self.run,route,'model-declared-recovery')

    def test_native_host_workspace_is_not_advertised_as_tool_filesystem(self):
        context='Task: t_example\nWorkspace: dir @ /controller/private/work/card\n## Body\nKeep every criterion.'
        visible=sandbox_context(context)
        self.assertNotIn('/controller/private',visible)
        self.assertIn('/workspace',visible)
        self.assertIn('Keep every criterion.',visible)
        self.assertEqual(sandbox_context(visible),visible)

    def test_missing_handoff_retains_output_policy_failure_without_sdk_response(self):
        result=dict(failed=True,api_calls=5,error='HTTP 422 output_budget_exceeds_policy SECRET-MUST-NOT-LEAK',
            messages=[{'content':'private conversation'}],final_response='private response')
        message=str(incomplete_activity(result,8192))
        self.assertIn('output_budget_exceeds_policy',message)
        self.assertIn('8192',message)
        self.assertNotIn('SECRET',message)
        self.assertNotIn('private',message)
        self.assertIn('missing_terminal_operation',str(incomplete_activity({},8192)))

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.project=Project.parse(configuration())
        self.store=Store(self.root/'private')
        self.workspace=self.root/'workspace';(self.workspace/'tests').mkdir(parents=True)
        (self.workspace/'app.py').write_text('VALUE = 1\n')
        (self.workspace/'tests/test_existing.py').write_text('baseline\n')
        self.snapshot=self.store.capture(self.workspace)
        self.run=Run('tests',1,'backend','tests',False,'backend','v1','contract')
        self.board=SimpleNamespace(ensure=lambda run:None,workspace=lambda run:self.workspace,
                                   input=lambda *args,**kwargs:self.snapshot)

    def test_only_new_tests_are_writable_in_tests_phase(self):
        sandbox=Sandbox(self.project,self.store,self.board,self.run)
        args=command(self.project,sandbox.expected)
        mounts=[args[index+1] for index,value in enumerate(args) if value=='--mount']
        self.assertIn('type=bind,src='+str(self.workspace)+',dst=/workspace,readonly',mounts)
        self.assertIn('type=bind,src='+str(self.workspace/'tests')+',dst=/workspace/tests',mounts)
        self.assertIn('type=bind,src='+str(self.workspace/'tests/test_existing.py')+
                      ',dst=/workspace/tests/test_existing.py,readonly',mounts)
        self.assertIn('--network',args);self.assertEqual(args[args.index('--network')+1],'none')
        self.assertIn('com.docker.compose.project='+self.project.namespace+'-tests',args)
        self.assertEqual(args[args.index('--user')+1],'65534:65534')
        self.assertIn('--read-only',args)

    def test_reviewer_source_is_exact_handoff_snapshot_not_mutable_workspace(self):
        red=self.store.record('red',self.run.binding(),dict(project=self.project.fingerprint(),snapshot=self.snapshot))
        self.board.input=lambda *args,**kwargs:red
        reviewing=Run('tests',2,'lead','tests',True,'backend','v1','contract')
        sandbox=Sandbox(self.project,self.store,self.board,reviewing)
        self.assertEqual(sandbox.workspace,self.store.tree(self.snapshot))
        mounts=command(self.project,sandbox.expected)
        self.assertEqual(mounts.count('--mount'),1)
        (self.workspace/'app.py').write_text('mutable author work\n')
        self.assertEqual((sandbox.workspace/'app.py').read_text(),'VALUE = 1\n')

    def test_changed_authority_or_invalid_phase_cannot_obtain_backend(self):
        sandbox=Sandbox(self.project,self.store,self.board,self.run)
        self.board.workspace=lambda run:self.root/'different'
        with self.assertRaises(ValueError):sandbox.ensure()
        invalid=Run('integration',3,'backend','integration',False,'backend','v1','contract')
        with self.assertRaises(ValueError):Sandbox(self.project,self.store,self.board,invalid)

    def test_regression_review_uses_the_same_central_immutable_evidence_policy(self):
        key=self.store.record('regression_red',self.run.binding(),dict(project=self.project.fingerprint(),snapshot=self.snapshot))
        self.board.input=lambda *args,**kwargs:key
        reviewing=Run('tests',2,'lead','tests',True,'backend','v1','contract')
        sandbox=Sandbox(self.project,self.store,self.board,reviewing)
        self.assertEqual(sandbox.workspace,self.store.tree(self.snapshot))
        self.assertEqual(command(self.project,sandbox.expected).count('--mount'),1)
        self.board.input=lambda *args,**kwargs:self.store.record('unrelated',self.run.binding(),dict(snapshot=self.snapshot))
        with self.assertRaises(ValueError):Sandbox(self.project,self.store,self.board,reviewing)

    def test_close_observes_uncertain_creation_without_repeating_or_forcing_removal(self):
        sandbox=Sandbox(self.project,self.store,self.board,self.run)
        cid='c'*64;exists=[False];calls=[]
        info=dict(Id=cid,Image=self.project.validation_image,State={'Running':False},
            Config=dict(User='65534:65534',Entrypoint=['/bin/sh'],Env=[],Labels={
                'fabriquinha.agent':sandbox.key,'com.docker.compose.project':self.project.namespace+'-tests'}),
            HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,CapDrop=['ALL']),
            Mounts=[dict(Type='bind',Source=str(source),Destination=target,RW=writable) for source,target,writable in (
                (self.workspace,'/workspace',False),(self.workspace/'tests','/workspace/tests',True),
                (self.workspace/'tests/test_existing.py','/workspace/tests/test_existing.py',False))])
        def docker(*args):
            calls.append(args)
            if args[0]=='create':
                exists[0]=True
                raise subprocess.TimeoutExpired(['docker','create'],30)
            if args[0]=='inspect':return json.dumps([info])
            if args[0]=='ps':return cid if exists[0] else ''
            if args[0]=='logs':return ''
            if args[0]=='rm':
                self.assertEqual(args,('rm',cid));exists[0]=False;return cid
            raise AssertionError(args)
        with patch('fabriquinha.hermes.docker',side_effect=docker):
            with self.assertRaises(Pending):sandbox.start()
            self.assertIsNone(sandbox.cid)
            sandbox.close()
        self.assertTrue(sandbox.closed)
        self.assertFalse(exists[0])
        self.assertEqual(sum(args[0]=='create' for args in calls),1)
        self.assertTrue((sandbox.folder/'retirement.json').is_file())
