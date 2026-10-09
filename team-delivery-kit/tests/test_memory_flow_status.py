import json
from pathlib import Path
import tempfile
import unittest

from memory_flow_status import KEY,publish,value

ISSUE='11111111-1111-4111-8111-111111111111'


class MemoryStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'status.json';self.calls=[]
        self.metadata={'planning_run':'TEST-1','sequence':'TEST-1-DELIVERY'}
        self.state={'stage':'admission_deferred','owner':'techlead','curation':{'admission':'capacity'}}
        self.lose_ack=False;self.apply=True

    def call(self,*args):
        self.calls.append(args)
        if args[1]=='list':return dict(self.metadata)
        self.assertEqual(args[:3],('metadata','set',ISSUE))
        self.assertEqual(json.loads(self.path.read_text())['stage'],'intent')
        if self.apply:self.metadata[KEY]=args[args.index('--value')+1]
        if self.lose_ack:raise TimeoutError('lost acknowledgement')
        return {}

    def publish(self):return publish(self.path,'TEST-1','a'*64,ISSUE,self.state,self.call)

    def writes(self):return [call for call in self.calls if call[1]=='set']

    def test_single_field_publication_is_idempotent_and_never_changes_status(self):
        self.assertEqual(self.publish(),'confirmed');self.assertEqual(self.publish(),'confirmed')
        self.assertEqual(len(self.writes()),1)
        body=json.loads(self.metadata[KEY]);self.assertEqual(body['admission'],'capacity')
        self.assertFalse(body['product_delivery_changed'])
        self.assertTrue(all(call[0]=='metadata' for call in self.calls))

    def test_lost_ack_is_confirmed_by_read_not_another_write(self):
        self.lose_ack=True;self.assertEqual(self.publish(),'confirmed');self.publish()
        self.assertEqual(len(self.writes()),1)

    def test_unknown_effect_never_replays_even_if_a_new_state_arrives(self):
        self.lose_ack=True;self.apply=False
        self.assertEqual(self.publish(),'observation_pending')
        self.state={'stage':'approved'}
        with self.assertRaisesRegex(ValueError,'observe prior'):self.publish()
        self.assertEqual(len(self.writes()),1)
        self.metadata[KEY]=json.loads(self.path.read_text())['value'];self.lose_ack=False;self.apply=True
        self.assertEqual(self.publish(),'confirmed');self.assertEqual(len(self.writes()),2)

    def test_binding_drift_prevents_mutation(self):
        self.metadata['planning_run']='OTHER-1'
        with self.assertRaisesRegex(ValueError,'binding'):self.publish()
        self.assertEqual(self.writes(),[])

    def test_projection_omits_model_text_credentials_and_approval_objects(self):
        body=json.loads(value('TEST-1',{'stage':'blocked','owner':'cto','reason':'do not publish',
            'token':'secret','curation':{'answer':{'decision':'approve'}}}))
        self.assertNotIn('token',body);self.assertNotIn('reason',body);self.assertNotIn('answer',body)
        for state in ({'stage':'blocked','owner':'ceo'},{'stage':'invented'},
                      {'stage':'approved','curation':{'issue_id':'invalid'}}):
            with self.assertRaises(ValueError):value('TEST-1',state)
