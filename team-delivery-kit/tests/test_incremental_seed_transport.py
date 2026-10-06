import copy
import json
import unittest
import test_incremental_harness_revision as fixtures
from broker import incremental_checkpoints as ledger


class SeedTransportRevisionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.HarnessRevisionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.con=f.con;f.prepare()
        state=ledger.status(self.con,'source');unit=state['units']['U1']
        unit['binding']={'issue_id':'revision3'}
        state.update(execution_authorized=True,activation={'issue_id':'revision3'})
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        self.previous=copy.deepcopy(state)
        self.receipt=dict(operation='cto_seed_transport_revision_v1',source_task='source',unit='U1',
            parent_issue='revision3',decision_task='transport-cto',cto='cto',proposal_sha256='a'*64,
            reason='Fixed pre-provider read transport; preserve all tests',experiment_sha256='9'*64,
            fixture_volume='owned-fixture',transport_sha256='8'*64,rejected_manifest_sha256='7'*64,
            proxy_image='sha256:'+'6'*64)

    def prepare(self,receipt=None):
        r=self.receipt if receipt is None else receipt
        return ledger.prepare_seed_transport_revision(self.con,'source',ledger.digest(r),lambda _:r)

    def test_one_transport_revision_preserves_all_previous_attempts_and_scope(self):
        state=self.prepare();u=state['units']['U1']
        self.assertEqual(u['revision'],4);self.assertEqual(len(u['history']),3)
        self.assertFalse(state['execution_authorized'])
        self.assertEqual(state['units']['U2'],self.previous['units']['U2'])
        self.assertEqual(state,self.prepare())
        for field in ('binding','red','test_review','green','delivery_review'):self.assertNotIn(field,u)

    def test_wrong_parent_scope_experiment_owner_and_proxy_are_rejected(self):
        for key,value in [('parent_issue','other'),('unit','U2'),('cto','author'),
            ('experiment_sha256','0'*64),('fixture_volume','other'),('proxy_image','mutable-tag')]:
            with self.assertRaises(ValueError):self.prepare({**self.receipt,key:value})
        self.assertEqual(ledger.status(self.con,'source'),self.previous)

    def test_accepted_red_cannot_be_discarded_by_transport_recovery(self):
        state=copy.deepcopy(self.previous);state['units']['U1']['red']='0'*64
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(ledger.status(self.con,'source'),state)

    def test_no_generic_revision_five_authority(self):
        self.prepare()
        with self.assertRaises(ValueError):self.prepare({**self.receipt,'decision_task':'another'})
