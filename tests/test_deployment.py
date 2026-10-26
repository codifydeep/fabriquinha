import sys
import unittest
import tempfile
import subprocess
import json
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.config import Project
from fabriquinha.deployment import web_spec, Deployment
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from test_delivery_core import configuration


class ComposeBoundaries(unittest.TestCase):
    def setUp(self):
        self.project=Project.parse(configuration())
        self.artifact=dict(image='sha256:'+'b'*64,commit='a'*40,snapshot='c'*64,receipt='d'*64,
                           project=self.project.fingerprint())

    def test_homologation_is_grouped_unprivileged_local_and_content_addressed(self):
        spec=web_spec(self.project,self.artifact,'effect')
        web=spec['services']['web']
        self.assertEqual(web['image'],self.artifact['image'])
        self.assertEqual(web['pull_policy'],'never')
        self.assertTrue(web['read_only'])
        self.assertEqual(web['user'],'65534:65534')
        self.assertEqual(web['cap_drop'],['ALL'])
        self.assertEqual(web['ports'][0]['host_ip'],'127.0.0.1')
        self.assertEqual(spec['networks']['default']['driver'],'bridge')
        self.assertTrue(spec['networks']['qa']['internal'])
        self.assertEqual(web['networks'],['default','qa'])
        self.assertNotIn('published',web['ports'][0])
        self.assertNotIn('volumes',web)
        self.assertNotIn('build',web)
        self.assertEqual(web['labels']['delivery-kit.lifecycle'],'homologation')

    def test_tag_or_foreign_artifact_cannot_be_deployed(self):
        for update in ({'image':'python:latest'},{'project':'other'}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                web_spec(self.project,{**self.artifact,**update},'effect')

    def test_real_delivery_uses_reserved_networks_without_implicit_allocation(self):
        project=Project.parse({**configuration(),'qualification':False,
            'coordination_roles':{'product':'backend','lead':'lead'},
            'delivery_roles':{'tests':'backend','integration':'lead'},'browser_image':'sha256:'+'b'*64})
        artifact={**self.artifact,'project':project.fingerprint()}
        networks=web_spec(project,artifact,'effect')['networks']
        self.assertEqual(networks,{suffix:dict(external=True,name=project.namespace+'-homologation_'+suffix)
            for suffix in ('default','qa')})

    def test_author_cannot_sign_the_independent_qa(self):
        delivery=Deployment.__new__(Deployment)
        delivery.board=SimpleNamespace(ensure=lambda run:None)
        for reviewing,actor,author in ((False,'author','author'),(True,'author','author')):
            run=SimpleNamespace(kind='integration',reviewing=reviewing,actor=actor,author=author)
            with self.assertRaises(ValueError):delivery.current(run,review=True)

    def test_deployment_receipt_keeps_overlapping_effect_and_observation_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'private')
            delivery=Deployment(self.project,store,SimpleNamespace(ensure=lambda run:None),None)
            delivery.journal=SimpleNamespace(do=lambda *args,**kwargs:dict(
                artifact=self.artifact['receipt'],container='container',healthy=True,image=self.artifact['image']))
            run=Run('integration',3,'lead','integration',False,'lead','v1','contract')
            key=delivery._up(run,self.artifact,'restore')
            value=store.receipt(key,kind='deployment')['payload']
            self.assertEqual(value['operation'],'restore')
            self.assertEqual(value['artifact'],self.artifact['receipt'])

    def test_failed_cli_stderr_is_archived_before_raising(self):
        with tempfile.TemporaryDirectory() as folder:
            delivery=Deployment.__new__(Deployment)
            result=subprocess.CompletedProcess(['docker','build'],1,stdout='before failure',stderr='build failed')
            with patch('fabriquinha.deployment.subprocess.run',return_value=result):
                with self.assertRaises(subprocess.CalledProcessError):
                    delivery._command(Path(folder),'build-output','build','fixture',timeout=30)
            saved=json.loads((Path(folder)/'build-output.json').read_bytes())
            self.assertEqual(saved['stderr'],'build failed')
            self.assertEqual(saved['returncode'],1)

    def test_network_readiness_requires_both_owned_networks_before_delivery(self):
        from fabriquinha.deployment import deployment_networks
        from fabriquinha.effects import EffectBlocked
        with patch('fabriquinha.deployment.docker',return_value='') as cli:
            with self.assertRaises(EffectBlocked):deployment_networks(self.project)
        self.assertTrue(all(call.args[:2]==('network','ls') for call in cli.call_args_list))

    def test_network_preparation_reserves_both_pools_and_is_idempotent(self):
        from fabriquinha.deployment import prepare_networks, deployment_networks
        state={};created=[];group=self.project.namespace+'-homologation'
        def cli(*args,**kwargs):
            if args[:2]==('network','ls'):
                return next((key for key,value in state.items() if args[-1]=='name=^'+value['Name']+'$'),'')
            if args[:2]==('network','inspect'):return json.dumps([state[args[2]]])
            self.assertEqual(args[:2],('network','create'))
            labels=dict(args[i+1].split('=',1) for i,a in enumerate(args) if a=='--label')
            key=str(len(state)+1)*64;created.append(args)
            state[key]=dict(Id=key,Name=args[-1],Driver='bridge',Internal='--internal' in args,
                Labels=labels,Scope='local',Ingress=False)
            return key
        with tempfile.TemporaryDirectory() as folder,patch('fabriquinha.deployment.docker',side_effect=cli):
            store=Store(Path(folder)/'private')
            first=prepare_networks(self.project,store)
            self.assertEqual(first,prepare_networks(self.project,store))
            self.assertEqual(len(created),2)
            self.assertEqual([x['name'] for x in deployment_networks(self.project)],[group+'_default',group+'_qa'])
            state['2'*64]['Internal']=False
            from fabriquinha.effects import EffectBlocked
            with self.assertRaises(EffectBlocked):deployment_networks(self.project)
            # A journal ACK is insufficient when current Docker policy drifted.
            with self.assertRaises(EffectBlocked):prepare_networks(self.project,store)
            self.assertEqual(len(created),2)

    def test_unknown_network_creation_is_observed_without_resending(self):
        from fabriquinha.deployment import prepare_networks
        from fabriquinha.effects import Pending
        calls=[]
        def cli(*args,**kwargs):
            calls.append(args)
            if args[:2]==('network','ls'):return ''
            raise subprocess.TimeoutExpired(['docker',*args],30)
        with tempfile.TemporaryDirectory() as folder,patch('fabriquinha.deployment.docker',side_effect=cli):
            store=Store(Path(folder)/'private')
            for _ in range(2):
                with self.assertRaises(Pending):prepare_networks(self.project,store)
            self.assertEqual(sum(args[:2]==('network','create') for args in calls),1)

    def test_foreign_network_is_preserved_without_creation(self):
        from fabriquinha.deployment import prepare_networks
        from fabriquinha.effects import EffectBlocked
        foreign=dict(Id='a'*64,Name=self.project.namespace+'-homologation_default',Driver='bridge',
            Internal=False,Scope='local',Ingress=False,Labels={'com.docker.compose.project':'toso-local'})
        def cli(*args,**kwargs):
            self.assertNotEqual(args[:2],('network','create'))
            return 'a'*64 if args[:2]==('network','ls') else json.dumps([foreign])
        with tempfile.TemporaryDirectory() as folder,patch('fabriquinha.deployment.docker',side_effect=cli):
            with self.assertRaises(EffectBlocked):prepare_networks(self.project,Store(Path(folder)/'private'))

    def test_lost_network_ack_settles_original_intent_by_observation(self):
        from fabriquinha.deployment import prepare_networks
        from fabriquinha.effects import Pending
        state={};creates=[]
        def cli(*args,**kwargs):
            if args[:2]==('network','ls'):
                return next((key for key,v in state.items() if args[-1]=='name=^'+v['Name']+'$'),'')
            if args[:2]==('network','inspect'):return json.dumps([state[args[2]]])
            creates.append(args);key=str(len(state)+1)*64
            labels=dict(args[i+1].split('=',1) for i,a in enumerate(args) if a=='--label')
            state[key]=dict(Id=key,Name=args[-1],Driver='bridge',Scope='local',Ingress=False,
                            Internal='--internal' in args,Labels=labels)
            if len(creates)==1:raise subprocess.TimeoutExpired(['docker',*args],30)
            return key
        with tempfile.TemporaryDirectory() as folder,patch('fabriquinha.deployment.docker',side_effect=cli):
            store=Store(Path(folder)/'private')
            with self.assertRaises(Pending):prepare_networks(self.project,store)
            self.assertEqual(len(prepare_networks(self.project,store)),2)
            self.assertEqual(len(creates),2)  # One per network, no retry of the first.
            effects=[json.loads(p.read_bytes()) for p in (store.root/'effects').glob('*.json')]
            self.assertEqual([x['state'] for x in effects],['done','done'])


if __name__=='__main__':unittest.main()
