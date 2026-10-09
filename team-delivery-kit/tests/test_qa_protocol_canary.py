import json
import unittest
from qa_protocol_canary import fixture,summary


class ProtocolCanaryTests(unittest.TestCase):
    def test_fixture_is_explicitly_synthetic_and_cannot_claim_delivery(self):
        body=fixture('test/model')
        self.assertEqual(body['model'],'test/model')
        self.assertIn('PROTOCOL FIXTURE ONLY',body['messages'][0]['content'])
        self.assertIn('no execution or diagnosis authority',body['messages'][0]['content'])
        self.assertEqual(body['max_tokens'],512)

    def test_summary_never_exposes_content_or_unrecognized_finish(self):
        secret='PRIVATE_RESPONSE_CONTENT'
        raw=('data: '+json.dumps({'choices':[{'delta':{'content':secret},
              'finish_reason':secret}]})+'\n\ndata: [DONE]\n\n').encode()
        proof=summary(raw,secret)
        self.assertNotIn(secret,json.dumps(proof))
        self.assertEqual(proof['finishes'],['other'])
        self.assertEqual(proof['media'],'other')
        self.assertEqual(proof['kind'],'protocol_fixture_not_delivery_evidence')

    def test_repeated_empty_terminal_is_observed_not_declared_delivery_success(self):
        raw=(''.join('data: '+json.dumps({'choices':[{'delta':{'content':''},
             'finish_reason':'stop'}]})+'\n\n' for _ in range(2))+'data: [DONE]\n\n').encode()
        proof=summary(raw,'text/event-stream')
        self.assertEqual(proof['finishes'],['stop','stop'])
        self.assertEqual(proof['after_finish'][0]['content_chars'],0)
        self.assertNotIn('delivery_approved',proof)
