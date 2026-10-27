"""Explicit small pools cannot collide with or replace unrelated Docker networks."""
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.config import Project,pool_subnets
from fabriquinha.artifacts import Store
from fabriquinha.deployment import prepare_networks,deployment_networks,network_identity
from fabriquinha.effects import Pending,EffectBlocked
from test_delivery_core import configuration


class NetworkPools(unittest.TestCase):
    def setUp(self):
        self.project=Project.parse({**configuration(),'network_pool':'10.245.248.0/26'})
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=Store(Path(temporary.name)/'private');self.state={};self.created=[];self.lost=False

    def cli(self,*args,**kwargs):
        if args[:2]==('network','ls'):
            if len(args)==3:return '\n'.join(self.state)
            return next((key for key,entry in self.state.items() if args[-1]=='name=^'+entry['Name']+'$'),'')
        if args[:2]==('network','inspect'):return json.dumps([self.state[key] for key in args[2:]])
        self.assertEqual(args[:2],('network','create'))
        self.assertIn('--subnet',args)
        self.created.append(args);key=str(len(self.state)+1)*64
        labels=dict(args[i+1].split('=',1) for i,arg in enumerate(args) if arg=='--label')
        self.state[key]=dict(Id=key,Name=args[-1],Driver='bridge',Scope='local',Ingress=False,
            Internal='--internal' in args,Labels=labels,IPAM={'Config':[{'Subnet':args[args.index('--subnet')+1]}]})
        if self.lost:self.lost=False;raise subprocess.TimeoutExpired(['docker',*args],30)
        return key

    def test_pool_is_private_aligned_bounded_and_legacy_fingerprints_do_not_change(self):
        self.assertEqual(pool_subnets('10.245.248.0/26'),
            {'default':'10.245.248.0/28','qa':'10.245.248.16/28','core':'10.245.248.32/28'})
        for value in ('127.0.0.0/26','8.8.8.0/26','169.254.0.0/26','10.1.1.1/26','10.1.1.0/24','fd00::/26',True):
            with self.subTest(value=value),self.assertRaises(ValueError):Project.parse({**configuration(),'network_pool':value})
        legacy=Project.parse(configuration());explicit_none=Project.parse({**configuration(),'network_pool':None})
        self.assertEqual(legacy.fingerprint(),'d12629c7130d402ce22561914b18386d7d88be73685ab2f1bdaa7ca5f2180274')
        self.assertEqual(legacy.fingerprint(),explicit_none.fingerprint());self.assertNotEqual(legacy.fingerprint(),self.project.fingerprint())

    def test_create_once_reobserve_ipam_and_never_reuse_a_drifted_network(self):
        with patch('fabriquinha.deployment.docker',side_effect=self.cli):
            first=prepare_networks(self.project,self.store)
            self.assertEqual(first,prepare_networks(self.project,self.store));self.assertEqual(len(self.created),2)
            self.assertEqual(self.state['1'*64]['IPAM']['Config'][0]['Subnet'],'10.245.248.0/28')
            self.assertEqual(self.state['2'*64]['IPAM']['Config'][0]['Subnet'],'10.245.248.16/28')
            self.state['2'*64]['IPAM']['Config'][0]['Subnet']='10.245.249.0/28'
            with self.assertRaises(EffectBlocked):deployment_networks(self.project)
            with self.assertRaises(EffectBlocked):prepare_networks(self.project,self.store)
            self.assertEqual(len(self.created),2)

    def test_foreign_overlap_including_core_is_refused_before_any_creation_intent(self):
        for subnet in ('10.245.248.0/28','10.245.248.32/28','10.245.248.48/28','10.245.248.0/24'):
            self.state={'a'*64:dict(Id='a'*64,Name='toso-local_network',Driver='bridge',Labels={},IPAM={'Config':[{'Subnet':subnet}]})}
            with self.subTest(subnet=subnet),patch('fabriquinha.deployment.docker',side_effect=self.cli):
                with self.assertRaises(EffectBlocked):prepare_networks(self.project,self.store)
            self.assertEqual(self.created,[]);self.assertEqual(len(self.state),1)
            self.assertEqual(list((self.store.root/'effects').glob('*.json')),[])

    def test_lost_create_ack_is_adopted_without_another_create(self):
        self.lost=True
        with patch('fabriquinha.deployment.docker',side_effect=self.cli):
            with self.assertRaises(Pending):prepare_networks(self.project,self.store)
            self.assertEqual(len(prepare_networks(self.project,self.store)),2)
        self.assertEqual(len(self.created),2)
        identities=[json.loads(path.read_bytes())['identity'] for path in (self.store.root/'effects').glob('*.json')]
        self.assertTrue(all(value['version']==2 and 'subnet' in value for value in identities))
        self.assertIn(network_identity(self.project,'qa'),identities)

    def test_existing_core_pool_needs_exact_compose_and_project_ownership(self):
        core=dict(Id='a'*64,Name=self.project.namespace+'_default',Driver='bridge',Scope='local',Ingress=False,Internal=False,
            IPAM={'Config':[{'Subnet':'10.245.248.32/28'}]},Labels={'com.docker.compose.project':self.project.namespace,
                'com.docker.compose.network':'default','fabriquinha.project':self.project.fingerprint()})
        self.state={'a'*64:core}
        with patch('fabriquinha.deployment.docker',side_effect=self.cli):
            self.assertEqual(len(prepare_networks(self.project,self.store)),2)
            core['Labels']['fabriquinha.project']='foreign'
            with self.assertRaises(EffectBlocked):prepare_networks(self.project,self.store)
        self.assertEqual(len(self.created),2)


if __name__=='__main__':unittest.main()
