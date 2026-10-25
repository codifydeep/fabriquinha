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
            tools=[dict(type='function',function={'name':'brief_submit','parameters':{'type':'object'}})],max_tokens=9999)
        self.assertEqual(self.send(body),(200,b'{"choices":[]}'))
        sent=self.app.forward.call_args.args[0]
        self.assertEqual(sent['messages'],body['messages']);self.assertEqual(sent['tools'],body['tools'])
        self.assertEqual(sent['max_tokens'],4096)

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
