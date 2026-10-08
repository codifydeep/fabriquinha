import copy
from contextlib import contextmanager
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import indicator_experiment as probe,test_first_job,harness_qualification


class IndicatorExperimentTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(source_task='source',manifest_sha256='a'*64,volume='snapshot',issue_id='issue',
            author='author',minimum_calls=8,diagnostic={'test_sha256':'b'*64},post_execution_diagnosis={"operation":"fixed"})
        self.proof=dict(operation='fixed_indicator_write_hypothesis_v1',status='supported',
            original_manifest_sha256='a'*64,original_test_sha256='b'*64,
            variant_manifest_sha256='c'*64,variant_test_sha256='d'*64,variant_file_bytes=31955,
            inputs_unchanged=True,original_test_bodies_unchanged=True,diagnostic_copy_only=True,
            fits_existing_file_limit=True,valid_red_green_receipt=False,author_retry_authorized=False,
            delivery_approval=False,variant={},baseline_observation=dict(tests=15,failures=11,errors=0,
                skipped=0,unexpected_successes=0,expected_failures=0))
        self.state=dict(stage='plan_qualified',cto_task='cto-task',peer_task='peer-task',
            cto_decision={'action':'request_test_revision'},peer_decision={'action':'request_test_revision'})
        self.saved=[];self.wakes=[]
        @contextmanager
        def db():yield None
        self.b=SimpleNamespace(db=db,OWNER='owner',docker=lambda *a:{'Labels':{
            'delivery-kit.owner':'owner','delivery-kit.test-first-task':'source'}})
        self.fx=SimpleNamespace(remaining_calls=lambda:100,implementation_available=lambda *a:True,
            ensure_wakeup=self.wakeup)

    def save(self,state):self.saved.append(copy.deepcopy(state))
    def wakeup(self,*args,**kw):
        self.wakes.append((args,kw));self.assertEqual(self.saved[-1]['indicator_experiment']['stage'],'author_intent')
        return {'id':'wake'}

    def test_exact_experiment_before_one_author_dispatch_no_gate_approval(self):
        result=dict(exit_code=0,output=json.dumps(self.proof),container_id='exact',output_sha256='e'*64)
        with patch.object(harness_qualification,'validate_result'),patch.object(test_first_job,'run',return_value=result) as job:
            state=probe.advance(self.b,self.config,self.state,self.fx,self.save)
            self.assertEqual(state['stage'],'author_dispatched')
            self.assertEqual(len(self.wakes),1)
            payload=job.call_args.args[-1]
            self.assertEqual(payload['Image'],probe.IMAGE)
            self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
            self.assertTrue(payload['HostConfig']['Mounts'][0]['ReadOnly'])
            self.assertIn('NOT the original app.js',self.wakes[0][0][-1])
            self.assertIn('genuine full-suite Red',self.wakes[0][0][-1])
            probe.advance(self.b,self.config,state,self.fx,self.save)
            self.assertEqual(job.call_count,1);self.assertEqual(len(self.wakes),1)

    def test_observation_timeout_no_author_and_ambiguous_wakeup_never_reposts(self):
        with patch.object(test_first_job,'run',side_effect=TimeoutError):
            state=probe.advance(self.b,self.config,self.state,self.fx,self.save)
        self.assertEqual(state['indicator_experiment']['stage'],'observing');self.assertEqual(self.wakes,[])
        state={**self.state,'indicator_experiment':dict(stage='author_intent',intent_at=10**12,
            proof=self.proof,proof_sha256=probe.digest(self.proof))}
        self.fx.ensure_wakeup=lambda *args,**kw:self.assertFalse(kw['allow_create'])
        with patch.object(harness_qualification,'validate_result'):
            probe.advance(self.b,self.config,state,self.fx,self.save)

    def test_wrong_snapshot_approval_size_or_no_baseline_failure_rejected(self):
        for changes in ({'original_manifest_sha256':'wrong'},{'delivery_approval':True},
                        {'variant_file_bytes':32769},{'fits_existing_file_limit':False},
                        {'variant_test_sha256':'b'*64},{'baseline_observation':{'tests':15,'failures':0}}):
            with patch.object(harness_qualification,'validate_result'),self.assertRaises(ValueError):
                probe.validate({**self.proof,**changes},self.config)
