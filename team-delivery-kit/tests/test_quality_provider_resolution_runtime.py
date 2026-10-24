"""Real private-file effects with synthetic HTTP; no real key/provider/model."""
import contextlib
import io
import json
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import quality_provider_resolution as contract
import quality_review_provider_access as host
from test_quality_provider_resolution import facts


class QualityProviderResolutionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.counter=self.root/'calls.json'
        self.counter.write_text('{"calls": 17}');self.before=self.counter.read_bytes()
        self.pause=self.root/'provider-pause.json';self.pause.write_text(json.dumps(facts()['resolution']['pause']))
        source=self.root/'model_proxy.py';source.write_text('# synthetic proxy source only\n')
        self.module=SimpleNamespace(COUNTER_PATH=str(self.counter),MAX_CALLS=10000,__file__=str(source),
            load_calls=lambda:json.loads(self.counter.read_bytes())['calls'],
            provider_pause=lambda:json.loads(self.pause.read_bytes()) if self.pause.exists() else None)
        value=facts();self.operation=value['maintenance_operation']
        self.payload={k:value[k] for k in ('namespace','maintenance_operation','request_id','proxy_container',
            'proxy_image','event','operator_confirmed')}
        self.payload['event']['started_at']=time.time()-5
        self.http=[];self.credits=dict(total_credits=10.,total_usage=2.)
        self.key=dict(limit=5.,limit_remaining=3.)
        original=Path.read_text
        def read_text(path,*args,**kwargs):
            return 'fixture-not-a-real-key' if str(path)=='/secret/openrouter.key' else original(path,*args,**kwargs)
        for target in (patch.object(Path,'read_text',read_text),patch.dict(sys.modules,{'model_proxy':self.module}),
                patch('urllib.request.urlopen',side_effect=self.official)):
            target.start();self.addCleanup(target.stop)

    def official(self,request,timeout):
        endpoint=request.full_url
        self.assertIn(endpoint,('https://openrouter.ai/api/v1/credits','https://openrouter.ai/api/v1/key'))
        self.http.append(endpoint)
        data=self.credits if endpoint.endswith('/credits') else self.key
        return io.BytesIO(json.dumps(dict(data=data)).encode())

    def run_program(self,mode,payload=None,*,allow_pending=False):
        output=io.StringIO();namespace={};completed=False
        with patch.object(sys,'stdin',io.StringIO(json.dumps(payload or self.payload))),\
                patch.object(sys,'argv',['fixed-runtime']),contextlib.redirect_stdout(output):
            try:
                exec(compile(contract.program(mode),'<fixed-payment-runtime>','exec'),namespace)
                completed=True
            except SystemExit as error:
                if not allow_pending or error.code!=0:raise
            finally:
                # Docker's isolated Python process closes these on exit. This
                # in-process fixture must provide that same FD boundary.
                if not completed and 'lock' in namespace:
                    try:os.close(namespace['lock'])
                    except OSError:pass
        return json.loads(output.getvalue())

    def test_resolve_then_observe_preserves_counter_without_another_http_request(self):
        result=self.run_program('resolve')
        self.assertEqual(len(self.http),2);self.assertFalse(self.pause.exists())
        self.assertEqual(self.counter.read_bytes(),self.before)
        self.assertFalse(result['delivery_approval']);self.assertEqual(result['model_calls'],0)
        second=self.run_program('observe');self.assertEqual(result,second);self.assertEqual(len(self.http),2)
        self.assertNotIn('fixture-not-a-real-key',json.dumps(result))

    def test_no_human_confirmation_prevents_http_and_pause_mutation(self):
        with self.assertRaises(AssertionError):self.run_program('resolve',{**self.payload,'operator_confirmed':False})
        self.assertEqual(self.http,[]);self.assertTrue(self.pause.exists());self.assertEqual(self.counter.read_bytes(),self.before)

    def test_no_credit_or_zero_key_allowance_preserves_pause(self):
        for credits,key in ((dict(total_credits=1.,total_usage=1.),self.key),
                (self.credits,dict(limit=5.,limit_remaining=0.))):
            self.credits,self.key=credits,key
            with self.assertRaises(ValueError):self.run_program('resolve')
            self.assertTrue(self.pause.exists());self.assertEqual(self.counter.read_bytes(),self.before)

    def test_explicit_unlimited_key_with_real_positive_account_is_supported(self):
        self.key=dict(limit=None,limit_remaining=None)
        result=self.run_program('resolve');self.assertTrue(result['resolution']['key_remaining_positive'])
        self.assertEqual(len(self.http),2);self.assertFalse(self.pause.exists())

    def test_invalid_credit_or_unknown_key_allowance_cannot_clear_pause(self):
        for credits,key in ((dict(total_credits=True,total_usage=0),dict(limit=5.,limit_remaining=1.)),
                (dict(total_credits=float('inf'),total_usage=0),self.key),
                (dict(total_credits=10.,total_usage=2.),dict(limit_remaining=None)),
                (dict(total_credits=10.,total_usage=2.),dict(limit=5.,limit_remaining=True))):
            self.credits,self.key=credits,key
            with self.assertRaises(ValueError):self.run_program('resolve')
            self.assertTrue(self.pause.exists());self.assertEqual(self.counter.read_bytes(),self.before)

    def test_observation_of_missing_receipt_makes_no_http_or_resolution(self):
        with self.assertRaises(SystemExit):self.run_program('observe')
        self.assertEqual(self.http,[]);self.assertTrue(self.pause.exists())

    def test_partial_resolution_is_observed_then_finished_without_new_http(self):
        unlink=Path.unlink
        def interrupt(path,*args,**kwargs):
            if path==self.pause:raise OSError('synthetic interruption after receipt')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupt),self.assertRaises(OSError):self.run_program('resolve')
        self.assertEqual(len(self.http),2);self.assertTrue(self.pause.exists())
        observed=self.run_program('observe',allow_pending=True)
        self.assertEqual(observed['stage'],'resolution_incomplete');self.assertTrue(self.pause.exists())
        result=self.run_program('finish')
        self.assertFalse(self.pause.exists());self.assertEqual(len(self.http),2)
        self.assertEqual(result['counter']['calls'],17);self.assertEqual(self.counter.read_bytes(),self.before)

    def test_live_resolver_lock_is_not_treated_as_missing_or_restarted(self):
        lock=self.counter.with_name('provider-resolution-'+self.operation+'.lock')
        fd=os.open(lock,os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            value=self.run_program('observe',allow_pending=True)
            self.assertEqual(value['stage'],'in_progress');self.assertEqual(self.http,[])
            self.assertTrue(self.pause.exists())
        finally:os.close(fd)


class QualityProviderHostTests(unittest.TestCase):
    def test_no_confirmation_touches_no_service_or_private_state(self):
        for function in (host.resolve,host.register):
            args=['delivery-kit-test','sha256:'+'1'*64,*['a0000000-0000-4000-8000-000000000001']*3]
            if function is host.register:args+=['a0000000-0000-4000-8000-000000000002']
            with self.subTest(function=function.__name__),patch.object(host,'Authority',side_effect=AssertionError('no effect')):
                with self.assertRaises(ValueError):function(*args)

    def test_only_exact_logged_upstream_402_without_later_success_is_accepted(self):
        value=facts()['event'];raw=json.dumps(value)
        self.assertEqual(host.event_from_logs(raw,value['execution_id']),value)
        for text in (raw+'\n'+raw,json.dumps({**value,'status':403}),
                raw+'\n'+json.dumps({**value,'status':200,'started_at':value['started_at']+1})):
            with self.assertRaises(ValueError):host.event_from_logs(text,value['execution_id'])

    def test_uncertain_resolution_can_only_observe_not_resubmit(self):
        value=facts();source='a0000000-0000-4000-8000-000000000004'
        previous='a0000000-0000-4000-8000-000000000005';image='sha256:'+'a'*64
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);(root/'model_proxy.py').write_text('# fixture proxy source\n')
            proxy=dict(Id=value['proxy_container'],Image=value['proxy_image'],Name='/delivery-kit-test-model-proxy-1',
                State=dict(Running=True),Config=dict(User='10000:10000',Labels={
                    'com.docker.compose.project':'delivery-kit-test','com.docker.compose.service':'model-proxy'}))
            identity=dict(namespace='delivery-kit-test',image=image,source=source,previous=previous,
                operation=value['maintenance_operation'],resolver_sha256=contract.source_sha256())
            payload={k:value[k] for k in ('namespace','maintenance_operation','request_id','proxy_container',
                'proxy_image','event','operator_confirmed')}
            host.save(root/'resolution-state.json',dict(identity=identity,stage='resolution_intent',
                proxy=host.same_proxy('delivery-kit-test',proxy),payload=payload))
            authority=SimpleNamespace(identity='6'*64,inspect_controller=lambda:'6'*64)
            no_result=SimpleNamespace(returncode=0,stdout=json.dumps(dict(stage='not_observed',model_calls=0,delivery_approval=False)),stderr='')
            with patch.object(host,'Authority',return_value=authority),patch.object(host,'archive',return_value=root),\
                    patch.object(host,'inspect',return_value=proxy),\
                    patch.object(host,'require_idle',return_value=(dict(operation_id=value['maintenance_operation']),{})),\
                    patch.object(host,'effect',return_value=no_result) as run:
                args=('delivery-kit-test',image,source,previous,value['maintenance_operation'])
                with self.assertRaises(ValueError):host.resolve(*args,confirmed=True)
                run.assert_not_called()
                result=host.resolve(*args,confirmed=True,observe=True)
                self.assertEqual(result['stage'],'not_observed');self.assertEqual(run.call_count,1)
                self.assertTrue(run.call_args.args[0][-1].startswith("mode='observe'"))
                self.assertEqual(json.loads(host.read(root/'resolution-state.json'))['stage'],'resolution_intent')

    def test_uncertain_registration_queries_existing_record_without_replaying(self):
        value=facts();source='a0000000-0000-4000-8000-000000000004'
        previous='a0000000-0000-4000-8000-000000000005';image='sha256:'+'a'*64
        qualification='a0000000-0000-4000-8000-000000000006'
        payment_qualification='a0000000-0000-4000-8000-000000000007'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700)
            payload=dict(source_task=source,previous_task=previous,maintenance_operation=value['maintenance_operation'],
                qualification={},provider_resolution=value,runtime_identity=dict(image=image,container_id='1'*64))
            identity=dict(namespace='delivery-kit-test',image=image,source=source,previous=previous,
                operation=value['maintenance_operation'],qualification_id=qualification,payment_qualification=payment_qualification)
            host.save(root/'registration-state.json',dict(identity=identity,stage='registration_intent',payload=payload))
            authority=SimpleNamespace(identity='6'*64,inspect_controller=lambda:'6'*64)
            reply=dict(stage='registered',model_calls=0,delivery_approval=False,tests_approved=False,incident_closed=False,marker='7'*64)
            effect=SimpleNamespace(returncode=0,stdout=json.dumps(reply),stderr='')
            with patch.object(host,'Authority',return_value=authority),patch.object(host,'archive',return_value=root),\
                    patch.object(host,'effect',return_value=effect) as run:
                args=('delivery-kit-test',image,source,previous,value['maintenance_operation'],qualification)
                with self.assertRaises(ValueError):host.register(*args,payment_qualification=payment_qualification,confirmed=True)
                run.assert_not_called()
                self.assertEqual(host.register(*args,payment_qualification=payment_qualification,confirmed=True,observe=True),reply)
                self.assertEqual(run.call_args.args[0][-1],'observe')
                self.assertEqual(json.loads(run.call_args.kwargs['input']),payload)


if __name__=='__main__':unittest.main()
