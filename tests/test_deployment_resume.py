"""Lost Docker acknowledgments across claims, using a deterministic transport.

No Docker/model/GitHub calls. Physical qualification is a separate test driver.
"""
from dataclasses import replace
import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_browser_contract import scenario
from test_delivery_core import configuration
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.deployment import Deployment
from fabriquinha.effects import Pending, EffectBlocked


class DeploymentContinuation(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.store=Store(self.root/'private')
        self.project=Project.parse(configuration())
        self.run=Run('integration',3,'lead','integration',False,'lead','v1','contract')
        self.active=self.run
        self.review='approved-review'; self.commit='a'*40
        source=self.root/'source'; (source/'tests').mkdir(parents=True)
        (source/'app.py').write_text('VALUE = 1\n')
        (source/'tests/qa.json').write_text(json.dumps(scenario()))
        self.snapshot=self.store.capture(source)
        self.publication=self.store.record('publication',self.run.binding(),dict(
            project=self.project.fingerprint(),review=self.review,snapshot=self.snapshot,
            merge_sha=self.commit))
        self.integrated=self.store.record('integrated',self.run.binding(),dict(
            project=self.project.fingerprint(),publication=self.publication,snapshot=self.snapshot,
            commit=self.commit,ci={'ok':True,'head_sha':self.commit}))
        def ensure(run):
            if run!=self.active: raise ValueError('obsolete claim')
        self.board=SimpleNamespace(ensure=ensure,input=lambda run,name:self.review)
        self.repo=SimpleNamespace(remote_head=lambda branch:self.commit)
        self.delivery=Deployment(self.project,self.store,self.board,None)
        self.images={};self.builds=[];self.deploys=[];self.live=None
        self.lose_build=False;self.lose_deploy=None
        self.addCleanup(patch.stopall)
        patch('fabriquinha.deployment.docker',side_effect=self.docker).start()
        patch.object(Deployment,'_command',side_effect=self.command).start()
        patch.object(Deployment,'service',side_effect=self.service).start()

    def docker(self,*args,**kwargs):
        if args[:2]==('image','inspect'):
            if args[2] not in self.images:raise subprocess.CalledProcessError(1,['docker'])
            return json.dumps([self.images[args[2]]])
        if args[:3]==('network','ls','-q'):return ''
        if args[0]=='logs':return 'preserved logs'
        raise AssertionError(args)

    def command(self,folder,name,*args,**kwargs):
        if args[0]=='build':
            self.builds.append(args)
            labels=dict(args[index+1].split('=',1) for index,value in enumerate(args) if value=='--label')
            tag=args[args.index('-t')+1]
            self.images[tag]=dict(Id='sha256:'+'b'*64,Config=dict(User='65534:65534',
                Entrypoint=['python','-B','/app/app.py','8080'],Labels=labels))
            if self.lose_build:
                self.lose_build=False
                raise subprocess.TimeoutExpired(['docker','build'],90)
        elif args[0]=='compose':
            spec=json.loads(Path(args[args.index('-f')+1]).read_bytes())['services']['web']
            artifact=spec['labels']['fabriquinha.artifact']
            self.deploys.append(artifact)
            self.live=dict(container='container-'+str(len(self.deploys)),artifact=artifact,
                image=spec['image'],healthy=True,url='http://127.0.0.1:1234',network='fixture')
            self.effect=spec['labels']['fabriquinha.effect']
            if artifact==self.lose_deploy:
                self.lose_deploy=None
                raise subprocess.TimeoutExpired(['docker','compose'],60)
        else:raise AssertionError(args)
        return ''

    def service(self,artifact=None,*,effect=None):
        if not self.live:return None
        if artifact and artifact['receipt']!=self.live['artifact']:return None
        if effect and effect!=self.effect:return None
        return dict(self.live)

    def reclaim(self):
        self.active=replace(self.active,number=self.active.number+1)
        self.delivery=Deployment(self.project,self.store,self.board,None)
        return self.active

    def test_build_ack_lost_then_new_claim_observes_same_image_and_origin(self):
        self.lose_build=True
        with self.assertRaises(Pending):
            self.delivery.artifact(self.run,self.integrated,self.repo)
        current=self.reclaim()
        artifact=self.delivery.artifact(current,self.integrated,self.repo)
        record=self.store.receipt(artifact,kind='artifact')
        self.assertEqual(record['binding'],self.run.binding())
        self.assertEqual(record['payload']['integrated'],self.integrated)
        self.assertEqual(len(self.builds),1)
        self.assertEqual(self.delivery.artifact(current,self.integrated,self.repo),artifact)
        with self.assertRaises(ValueError):self.delivery.artifact(self.run,self.integrated,self.repo)

    def test_changed_review_or_foreign_execution_cannot_reuse_integrated_result(self):
        self.reclaim();self.review='different-review'
        with self.assertRaises(ValueError):
            self.delivery.artifact(self.active,self.integrated,self.repo)
        self.review='approved-review'
        self.active=replace(self.active,contract='different-contract')
        with self.assertRaises(ValueError):
            self.delivery.artifact(self.active,self.integrated,self.repo)
        self.assertEqual(self.builds,[])

    def test_equivalent_revalidation_receipt_does_not_build_another_image(self):
        artifact=self.delivery.artifact(self.run,self.integrated,self.repo)
        current=self.reclaim()
        rechecked=self.store.record('integrated',current.binding(),
                                   self.store.receipt(self.integrated)['payload'])
        self.assertEqual(self.delivery.artifact(current,rechecked,self.repo),artifact)
        self.assertEqual(self.store.receipt(artifact)['payload']['integrated'],self.integrated)
        self.assertEqual(len(self.builds),1)

    def test_rollout_resumes_after_candidate_ack_loss_without_redeploying_steps(self):
        candidate=self.delivery.artifact(self.run,self.integrated,self.repo)
        payload=self.store.receipt(candidate)['payload']
        previous=self.store.record('artifact',self.run.binding(),{**payload,
            'role':'bootstrap','image':'sha256:'+'c'*64})
        self.lose_deploy=candidate
        with self.assertRaises(Pending):self.delivery.rollout(self.run,candidate,previous,self.repo)
        current=self.reclaim()
        rollout=self.delivery.rollout(current,candidate,previous,self.repo)
        result=self.store.receipt(rollout,kind='rollout')
        steps=[self.store.receipt(step) for step in result['payload']['steps']]
        self.assertEqual([step['payload']['operation'] for step in steps],
                         ['bootstrap','candidate','rollback','restore'])
        self.assertEqual([step['binding']['number'] for step in steps],
                         [self.run.number,self.run.number,current.number,current.number])
        self.assertEqual(self.deploys,[previous,candidate,previous,candidate])
        self.assertEqual(self.delivery.rollout(current,candidate,previous,self.repo),rollout)
        self.assertEqual(len(self.deploys),4)

    def test_new_claim_cannot_reset_the_pending_deploy_deadline(self):
        candidate=self.delivery.artifact(self.run,self.integrated,self.repo)
        payload=self.store.receipt(candidate)['payload']
        previous=self.store.record('artifact',self.run.binding(),{**payload,
            'role':'bootstrap','image':'sha256:'+'c'*64})
        self.delivery.journal.clock=lambda:100
        self.lose_deploy=candidate
        with self.assertRaises(Pending):self.delivery.rollout(self.run,candidate,previous,self.repo)
        self.live['healthy']=False
        current=self.reclaim()
        self.delivery.journal.clock=lambda:221
        with self.assertRaises(EffectBlocked):self.delivery.rollout(current,candidate,previous,self.repo)
        self.assertEqual(self.deploys,[previous,candidate])

    def test_branch_advance_after_build_cannot_roll_out_old_candidate(self):
        candidate=self.delivery.artifact(self.run,self.integrated,self.repo)
        payload=self.store.receipt(candidate)['payload']
        previous=self.store.record('artifact',self.run.binding(),{**payload,
            'role':'bootstrap','image':'sha256:'+'c'*64})
        self.repo.remote_head=lambda branch:'f'*40
        with self.assertRaises(EffectBlocked):
            self.delivery.rollout(self.run,candidate,previous,self.repo)
        self.assertEqual(self.deploys,[])

    def test_branch_advance_before_or_during_qa_cannot_create_release_evidence(self):
        candidate=self.delivery.artifact(self.run,self.integrated,self.repo)
        payload=self.store.receipt(candidate)['payload']
        previous=self.store.record('artifact',self.run.binding(),{**payload,
            'role':'bootstrap','image':'sha256:'+'c'*64})
        rollout=self.delivery.rollout(self.run,candidate,previous,self.repo)
        self.active=replace(self.run,number=4,actor='cto',reviewing=True)
        self.board.input=lambda run,name,**kwargs:rollout if name=='rollout' else self.review
        observed=[]
        def browser(run,snapshot,commit):
            observed.append(commit)
            self.repo.remote_head=lambda branch:'f'*40
            return self.store.record('browser_job',run.binding(),dict(exit_code=0,infrastructure_error=None,
                identity=dict(snapshot=snapshot,commit=commit),screenshot_sha256='d'*64,
                report=dict(status='passed',source_sha=commit,checks=['greeting'],errors=[])))
        self.delivery.runner=SimpleNamespace(browser=browser)
        self.repo.remote_head=lambda branch:'f'*40
        with self.assertRaises(EffectBlocked):self.delivery.qa(self.active,rollout,self.repo)
        self.assertEqual(observed,[])
        self.repo.remote_head=lambda branch:self.commit
        def response(url,**kwargs):
            body={'status':'ok'} if url.endswith('/health') else {'source_sha':self.commit}
            return contextlib.nullcontext(SimpleNamespace(status=200,read=lambda n:json.dumps(body).encode()))
        with patch('fabriquinha.deployment.urllib.request.build_opener',
                   return_value=SimpleNamespace(open=response)):
            with self.assertRaises(EffectBlocked):self.delivery.qa(self.active,rollout,self.repo)
        self.assertEqual(observed,[self.commit])
        self.assertFalse(any(json.loads(path.read_bytes())['kind']=='release_evidence'
                             for path in (self.store.root/'receipts').glob('*.json')))
