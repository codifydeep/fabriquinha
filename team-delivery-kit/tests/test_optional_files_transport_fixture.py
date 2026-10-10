import json
import copy
import unittest
from optional_files_transport_fixture import body
from model_optional_files_smoke import command
from decision_schema import apply as schema
from typed_decision_contract import apply as typed
from technical_optional_files_feedback import enabled,opt_in
from artifact_read_evidence import observations


class OptionalFixtureTests(unittest.TestCase):
    def test_fixture_qualifies_opt_in_without_product_approval(self):
        canonical=typed(schema(body()));self.assertFalse(enabled(canonical))
        projected=opt_in(canonical);self.assertTrue(enabled(projected))
        self.assertEqual(projected['tools'],canonical['tools'])
        self.assertNotIn('approve',projected['tools'][0]['function']['parameters']['properties']['action']['enum'])

    def test_invalid_zero_based_or_missing_fixture_reads_never_qualify(self):
        complete=body()
        self.assertEqual(len(observations(complete['messages'],wire=True)),2)
        invalid=copy.deepcopy(complete)
        for message in invalid['messages']:
            for call in message.get('tool_calls',[]):
                args=json.loads(call['function']['arguments']);args['offset']=0
                call['function']['arguments']=json.dumps(args)
        self.assertEqual(observations(invalid['messages'],wire=True),{})
        self.assertIs(opt_in(invalid),invalid)
        incomplete=copy.deepcopy(complete);incomplete['messages'].pop()
        self.assertIs(opt_in(incomplete),incomplete)

    def test_probe_embeds_same_fixture_and_has_no_product_mounts_or_docker_socket(self):
        cmd=command('delivery-kit-port2','sha256:'+'a'*64,'11111111-1111-4111-8111-111111111111')
        prefix=cmd[-1].split('request=urllib.request.Request',1)[0]
        namespace={};exec(prefix,namespace)
        expected=body()
        for key,value in expected.items():self.assertEqual(namespace['body'][key],value)
        self.assertIn('--rm',cmd)
        self.assertNotIn('/var/run/docker.sock',json.dumps(cmd))
        self.assertNotIn('/broker-state',json.dumps(cmd))
