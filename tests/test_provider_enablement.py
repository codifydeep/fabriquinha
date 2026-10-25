"""Enabling an existing policy cannot reset usage, clear holds or raise its cap."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from test_provider import policy
from fabriquinha.effects import write_json
from fabriquinha.provider import Policy

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('enable_provider',ROOT/'scripts/enable_hermes_provider.py')
operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)


class ProviderEnablement(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.policy=Policy.parse({**policy().values(),'enabled':False})
        write_json(self.root/'provider-policy.json',self.policy.values())
        write_json(self.root/'route.json',dict(base_url='http://127.0.0.1:19390/v1',
            model=self.policy.model,api_key=self.policy.client_token))
        self.state=dict(project=self.policy.project,policy=self.policy.fingerprint(),calls=7,max_calls=10,
            enabled=False,credential_present=True,provider_pause=None,relay_hold=None)
        self.connection=Mock();reply=self.connection.getresponse.return_value;reply.status=200
        reply.read.side_effect=lambda *a:json.dumps(self.state).encode()
        patched=patch.object(operator.http.client,'HTTPConnection',return_value=self.connection)
        patched.start();self.addCleanup(patched.stop)

    def test_exact_authorized_metadata_enables_only_existing_policy(self):
        result=operator.enable(self.root,7,10)
        actual=Policy.parse(json.loads((self.root/'provider-policy.json').read_bytes()))
        self.assertTrue(actual.enabled);self.assertEqual(actual.max_calls,10)
        self.assertEqual(actual.client_token,self.policy.client_token);self.assertEqual(result['model_calls'],0)
        self.connection.request.assert_called_once_with('GET','/status')

    def test_counter_or_hold_mismatch_preserves_disabled_policy(self):
        for update in (dict(calls=8),dict(provider_pause={'category':'payment'}),dict(relay_hold={'category':'unknown'}),
                       dict(credential_present=False),dict(policy='b'*64)):
            original=dict(self.state);self.state.update(update)
            with self.subTest(update=update),self.assertRaises(ValueError):operator.enable(self.root,7,10)
            self.assertEqual(json.loads((self.root/'provider-policy.json').read_bytes()),self.policy.values())
            self.state=original

    def test_requested_increase_is_not_allowed_and_no_metadata_call_is_made(self):
        with self.assertRaises(ValueError):operator.enable(self.root,7,11)
        self.connection.request.assert_not_called()


if __name__=='__main__':unittest.main()
