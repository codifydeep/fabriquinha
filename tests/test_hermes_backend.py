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
from fabriquinha.hermes import Sandbox, command
from fabriquinha.effects import Pending
from test_delivery_core import configuration


class NativeBackendPolicy(unittest.TestCase):
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
