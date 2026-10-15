import copy
import json
import unittest
from broker.calibration_objection import from_task
from generic_harness_calibration import digest
from calibration_response_contract import capsule,context


class ObjectionTests(unittest.TestCase):
    def setUp(self):
        self.c=dict(cto='cto',reviewer='lead',issue_id='issue',author_task='author',test_files=['tests/test.py'],
            prepared=dict(manifest_sha256='a'*64),calibration_engine='unittest_path_fixtures_v2')
        self.paths=['/evidence/'+root+'/tests/test.py' for root in ('candidate','previous')]
        self.t=dict(id='producer',agent_id='cto',issue_id='issue',wakeup_id='wake',status='completed',
            handoff_note=capsule(context('bundle',self.paths,digest(self.c),engine='unittest_path_fixtures_v2')),
            result=dict(output=json.dumps(dict(action='calibration_objection',reason='Inspect Node seam',execution_authorized=False,delivery_approval=False))))
        self.reads={p:dict(lines=20,total_lines=20) for p in self.paths}

    def test_authenticated_objection_preserves_reason_identity_and_full_reads(self):
        value=from_task(self.c,self.t,'wake','execution',self.reads)
        self.assertEqual(value['reason'],'Inspect Node seam');self.assertEqual(value['source_sha256'],digest(self.c))
        self.assertFalse(value['author_retry_authorized']);self.assertFalse(value['delivery_approval'])

    def test_wrong_actor_partial_reads_forged_flags_or_context_are_not_objections(self):
        for field,value in (('agent_id','author'),('status','failed'),('handoff_note','not a capsule'),('wakeup_id','foreign')):
            t={**self.t,field:value}
            with self.assertRaises(ValueError):from_task(self.c,t,'wake','execution',self.reads)
        with self.assertRaises(ValueError):from_task(self.c,self.t,'wake','execution',{})
        t=copy.deepcopy(self.t);v=json.loads(t['result']['output']);v['delivery_approval']=True;t['result']['output']=json.dumps(v)
        with self.assertRaises(ValueError):from_task(self.c,t,'wake','execution',self.reads)
