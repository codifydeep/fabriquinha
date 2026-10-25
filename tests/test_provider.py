"""Neutral relay: preserve meter/pause; no inference or legacy tool adapters."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.effects import write_json
from fabriquinha.provider import Policy,Ledger,Relay,Held,admit


def policy(**changes):
    return Policy.parse(dict(version=1,project='a'*64,model='example/model',max_calls=10,max_output_tokens=4096,
        enabled=True,client_token='local-client-token-for-tests',**changes))


class NeutralProvider(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.meter=self.root/'meter';self.meter.mkdir(mode=0o700);write_json(self.meter/'calls.json',{'calls':7})
        self.key=self.root/'test.key';self.key.write_text('fixture-only-not-a-provider-key');self.key.chmod(0o600)
        self.app=Relay(policy(),self.meter,self.key)
        self.app.forward=Mock(return_value=(200,b'{"choices":[]}'))

    def send(self,body=None,auth='Bearer local-client-token-for-tests'):
        return self.app.handle(auth,json.dumps(body or dict(model='example/model',messages=[{'role':'user','content':'Hello'}])).encode())

    def test_counter_restarts_from_existing_value_not_zero(self):
        self.send();self.assertEqual(Ledger(self.meter,10).state()['calls'],8)
        restored=Relay(policy(),self.meter,self.key)
        self.assertEqual(restored.status()['calls'],8)

    def test_credentials_are_not_needed_to_read_metadata_and_auth_errors_do_not_spend(self):
        self.send(auth='Bearer wrong');self.assertEqual(self.app.status()['calls'],7)
        self.app.forward.assert_not_called()
        self.key.unlink();self.assertFalse(self.app.status()['ready'])
        self.send();self.assertEqual(self.app.status()['calls'],7)

    def test_old_payment_pause_survives_restart_and_prevents_forward(self):
        pause=dict(category='upstream_payment_required',upstream_status=402,call_number=7)
        write_json(self.meter/'provider-pause.json',pause)
        self.assertEqual(self.send()[0],402);self.app.forward.assert_not_called()
        self.assertEqual(self.app.status()['calls'],7)
        self.assertEqual(Relay(policy(),self.meter,self.key).status()['provider_pause'],pause)

    def test_limit_is_atomic_and_never_refunds_an_attempt(self):
        for _ in range(3):self.assertEqual(self.send()[0],200)
        self.assertEqual(self.send()[0],429);self.assertEqual(self.app.forward.call_count,3)
        self.assertEqual(self.app.status()['calls'],10)

    def test_model_stream_and_size_are_checked_before_spending(self):
        for body in (dict(model='other',messages=[{}]),dict(model='example/model',messages=[{}],stream=True),
                     dict(model='example/model',messages=[]),dict(model='example/model',messages=[{}],models=['other'])):
            self.assertEqual(self.send(body)[0],400)
        self.assertEqual(self.app.handle('Bearer local-client-token-for-tests',b'x'*(2*1024*1024+1))[0],413)
        self.assertEqual(self.app.status()['calls'],7);self.app.forward.assert_not_called()

    def test_legacy_markers_tools_and_provider_response_are_not_rewritten(self):
        body=dict(model='example/model',messages=[dict(role='user',content='[HERMES-DEMO] delivery_submit')],
            tools=[dict(type='function',function={'name':'brief_submit','parameters':{'type':'object'}})],max_tokens=4096)
        self.assertEqual(self.send(body),(200,b'{"choices":[]}'))
        sent=self.app.forward.call_args.args[0]
        self.assertEqual(sent['messages'],body['messages']);self.assertEqual(sent['tools'],body['tools'])
        self.assertEqual(sent['max_tokens'],4096)

    def test_retry_boost_above_real_output_cap_is_rejected_without_spending(self):
        for field in ('max_tokens','max_completion_tokens'):
            body=dict(model='example/model',messages=[dict(role='user',content='plan')],**{field:8192})
            status,data=self.send(body)
            self.assertEqual(status,422);self.assertEqual(json.loads(data)['error']['code'],'output_budget_exceeds_policy')
        self.assertEqual(self.app.status()['calls'],7);self.app.forward.assert_not_called()

    def test_explicit_16k_cap_is_preserved_and_a_32k_boost_is_still_refused(self):
        self.app.policy=Policy.parse({**policy().values(),'max_output_tokens':16384})
        body=dict(model='example/model',messages=[dict(role='user',content='bounded generation')],max_tokens=16384)
        self.assertEqual(self.send(body)[0],200)
        self.assertEqual(self.app.forward.call_args.args[0]['max_tokens'],16384)
        self.assertEqual(self.app.status()['calls'],8)
        self.assertEqual(self.send({**body,'max_tokens':32768})[0],422)
        self.assertEqual(self.app.status()['calls'],8)
        self.assertEqual(self.app.forward.call_count,1)

    def test_attempt_metadata_keeps_budget_and_finish_reason_not_conversations(self):
        response=dict(choices=[dict(finish_reason='length',message={'content':'private model text'})],
            usage=dict(prompt_tokens=100,completion_tokens=4096,total_tokens=4196))
        self.app.forward.return_value=(200,json.dumps(response).encode())
        status,data=self.send();self.assertEqual(status,200);self.assertEqual(json.loads(data),response)
        evidence=json.loads((self.meter/'attempts/8.json').read_bytes())
        self.assertEqual(evidence['finish_reasons'],['length']);self.assertEqual(evidence['requested_output'],4096)
        self.assertEqual(evidence['usage']['completion_tokens'],4096)
        self.assertNotIn('messages',evidence);self.assertNotIn('private model text',json.dumps(evidence))

    def test_transport_metadata_preserves_cause_and_never_retries_unknown_call(self):
        self.app.forward.side_effect=TimeoutError('private error details')
        self.assertEqual(self.send()[0],503)
        evidence=json.loads((self.meter/'attempts/8.json').read_bytes())
        self.assertEqual(evidence['error_type'],'TimeoutError');self.assertNotIn('private error details',json.dumps(evidence))
        self.assertEqual(self.send()[0],503);self.assertEqual(self.app.forward.call_count,1)

    def test_explicit_local_archive_preserves_consumed_call_and_is_idempotent(self):
        ledger=self.app.ledger;ledger.uncertain(7)
        receipt=ledger.archive_uncertain(7,'a'*32)
        self.assertEqual(receipt['calls_preserved'],7);self.assertFalse(receipt['retry_executed'])
        self.assertIsNone(ledger.state()['relay_hold']);self.assertEqual(ledger.state()['calls'],7)
        self.assertEqual(json.loads((self.meter/'hold-archives'/('a'*32)/'relay-hold.json').read_bytes()),
            dict(category='transport_unknown',call_number=7))
        ledger.reserve();ledger.uncertain(8)
        self.assertEqual(ledger.archive_uncertain(7,'a'*32),receipt)
        self.assertEqual(ledger.state()['relay_hold']['call_number'],8)
        with self.assertRaises(ValueError):ledger.archive_uncertain(8,'a'*32)

    def test_archive_resumes_after_delete_without_losing_recovery_copy(self):
        ledger=self.app.ledger;ledger.uncertain(7);save=ledger.save
        def interrupted(name,value):
            if name.endswith('/receipt.json'):raise OSError('fixture: interrupted final ACK')
            save(name,value)
        ledger.save=interrupted
        with self.assertRaises(OSError):ledger.archive_uncertain(7,'c'*32)
        self.assertIsNone(ledger.state()['relay_hold']);self.assertEqual(ledger.state()['calls'],7)
        ledger.save=save
        self.assertEqual(ledger.archive_uncertain(7,'c'*32)['calls_preserved'],7)

    def test_archive_refuses_changed_counter_financial_pause_or_an_active_owner(self):
        ledger=self.app.ledger;ledger.uncertain(7)
        with self.assertRaises(ValueError):ledger.archive_uncertain(6,'b'*32)
        with ledger.owner():
            with self.assertRaises(BlockingIOError):ledger.archive_uncertain(7,'b'*32)
        ledger.pause(7,402)
        with self.assertRaises(ValueError):ledger.archive_uncertain(7,'b'*32)
        self.assertEqual(ledger.state()['relay_hold']['call_number'],7)
        self.assertEqual(ledger.state()['provider_pause']['upstream_status'],402)

    def test_402_creates_old_compatible_pause_and_never_retries(self):
        self.app.forward.return_value=(402,b'private upstream body')
        first=self.send();self.assertEqual(first[0],402);self.assertNotIn(b'private',first[1])
        self.assertEqual(self.send()[0],402);self.assertEqual(self.app.forward.call_count,1)
        self.assertEqual(self.app.status()['calls'],8)
        value=json.loads((self.meter/'provider-pause.json').read_bytes())
        self.assertEqual(value,dict(category='upstream_payment_required',upstream_status=402,call_number=8))

    def test_unknown_transport_is_sticky_and_does_not_blindly_charge_again(self):
        self.app.forward.side_effect=TimeoutError('request may have reached provider')
        self.assertEqual(self.send()[0],503);self.assertEqual(self.send()[0],503)
        self.assertEqual(self.app.forward.call_count,1);self.assertEqual(self.app.status()['calls'],8)
        self.assertFalse(Relay(policy(),self.meter,self.key).status()['ready'])

    def test_disabled_corrupt_or_concurrent_relay_cannot_clear_the_barrier(self):
        self.app.policy=Policy.parse({**policy().values(),'enabled':False})
        self.assertEqual(self.send()[0],503);self.assertEqual(self.app.status()['calls'],7)
        with self.app.ledger.owner():
            with self.assertRaises(BlockingIOError):
                with self.app.ledger.owner():pass
        write_json(self.meter/'calls.json',{'calls':True})
        self.assertFalse(self.app.status()['ready'])
        self.assertEqual(self.send()[0],503);self.app.forward.assert_not_called()

    def test_admission_binds_project_model_policy_and_preserves_financial_pause(self):
        state=self.app.status()
        self.assertEqual(admit(self.app.policy,state,'a'*64)['remaining'],3)
        for changes in ({'project':'b'*64},{'model':'different/model'},{'policy':'b'*64},{'calls':True},{'neutral':False}):
            with self.subTest(changes=changes),self.assertRaises(Held):admit(self.app.policy,{**state,**changes},'a'*64)
        write_json(self.meter/'provider-pause.json',dict(category='upstream_payment_required',upstream_status=402,call_number=7))
        with self.assertRaises(Held) as caught:admit(self.app.policy,self.app.status(),'a'*64)
        self.assertEqual(caught.exception.status,402)
        self.assertEqual(json.loads((self.meter/'calls.json').read_bytes()),{'calls':7})

    def test_forward_setup_errors_also_hold_without_repeated_reservations(self):
        self.app.forward.side_effect=ValueError('credential format not usable')
        self.assertEqual(self.send()[0],503);self.assertEqual(self.send()[0],503)
        self.assertEqual(self.app.forward.call_count,1)


if __name__=='__main__':unittest.main()
