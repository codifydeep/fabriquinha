import json
import unittest
from unittest.mock import patch
import model_proxy
import probe_frozen_patch_provider as p


class FrozenPatchProviderTests(unittest.TestCase):
    def setUp(self):
        self.target='/workspace/tests/test_new.py'
        self.inputs=dict(issue_id='11111111-1111-4111-8111-111111111111',
            source_task='22222222-2222-4222-8222-222222222222',manifest_sha256='a'*64,
            target=self.target,sources=['/workspace/app/static/app.js'],
            files={self.target:"import unittest\nQUERY = 'calls.length'\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(QUERY)\n",
                '/workspace/app/static/app.js':'fetch("/health");\n'},
            context='Keep the service status indicator.',correction_reason='Count service-mode requests separately.')

    def reply(self,old="QUERY = 'calls.length'",new="QUERY = 'calls.filter(c => c.url === \"/service-mode\").length'"):
        return dict(choices=[dict(index=0,finish_reason='tool_calls',message=dict(tool_calls=[dict(
            function=dict(name='patch',arguments=json.dumps(dict(path=self.target,old_string=old,new_string=new))))]))])

    def test_frozen_fixture_selects_patch_without_claiming_native_reads(self):
        p.validate_inputs(self.inputs)
        with patch.object(p,'INPUT',self.inputs,create=True):
            body=model_proxy.validate_request(p.fixture(model_proxy.MODEL))
            self.assertEqual(body['tool_choice']['function']['name'],'patch')
            self.assertIn('NOT executed',body['messages'][0]['content'])
            receipt=p.validate_reply(self.reply())
            self.assertFalse(receipt['tools_executed'])
            self.assertTrue(receipt['proposed_assertions_unchanged'])
            self.assertNotIn('calls.filter',json.dumps(receipt))

    def test_noop_wrong_fragment_and_assertion_weakening_fail(self):
        with patch.object(p,'INPUT',self.inputs,create=True):
            for old,new in [('absent','new'),('self.assertTrue(QUERY)','self.assertTrue(True)'),('calls.length','calls.length')]:
                with self.assertRaises(ValueError):p.validate_reply(self.reply(old,new))

    def test_private_input_bounds_and_remote_intent_program(self):
        for changes in (dict(target='/workspace/app.py'),dict(manifest_sha256='wrong'),
                        dict(context='x'*16001),dict(sources=['/workspace/../secret'])):
            with self.assertRaises(ValueError):p.validate_inputs(dict(self.inputs,**changes))
        source=p.remote_program('33333333-3333-4333-8333-333333333333',self.inputs)
        compile(source,'frozen-diagnostic','exec')
        self.assertIn("'intent'",source)
        self.assertIn('historical_failure_cause_proven=False',source)
