import copy
import json
import unittest
import test_incremental_checkpoints as fixtures
from broker import incremental_checkpoints as ledger


class HarnessRevisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.IncrementalCheckpointTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.con=self.fixture.con
        receipt=self.fixture.repair_receipt()
        ledger.prepare_test_repair(self.con,'source','U1',ledger.digest(receipt),lambda _:receipt)
        state=self.fixture.state();unit=state['units']['U1']
        unit.update(stage='awaiting_green',binding={'issue_id':'repair2'},red='e'*64,test_review='f'*64)
        state.update(execution_authorized=True,activation={'issue_id':'repair2'})
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        self.previous=copy.deepcopy(state)
        self.receipt=dict(operation='cto_harness_experiment_revision_v1',source_task='source',unit='U1',
            parent_issue='repair2',decision_task='cto-experiment-task',cto='cto',original_red='e'*64,
            proposal_sha256='a'*64,reason='Actual selector experiment requires new matching and controls',
            experiment_sha256='9'*64,fixture_volume='owned-fixture')

    def prepare(self,receipt=None):
        receipt=self.receipt if receipt is None else receipt
        return ledger.prepare_harness_revision(self.con,'source',ledger.digest(receipt),lambda _:receipt)

    def test_new_revision_preserves_failures_without_reusing_permission(self):
        state=self.prepare();unit=state['units']['U1']
        self.assertEqual(unit['revision'],3)
        self.assertEqual(unit['stage'],'awaiting_red')
        self.assertEqual(unit['history'][-1],{k:v for k,v in self.previous['units']['U1'].items() if k!='history'})
        self.assertEqual(len(unit['history']),2)
        self.assertFalse(state['execution_authorized'])
        self.assertEqual(state['units']['U2'],self.previous['units']['U2'])
        for field in ('binding','red','test_review','green','delivery_review'):
            self.assertNotIn(field,unit)
        self.assertEqual(state,self.prepare())

    def test_wrong_parent_red_proposal_or_owner_is_rejected(self):
        for key,value in [('parent_issue','other'),('original_red','0'*64),
            ('proposal_sha256','0'*64),('cto','author'),('reason','')]:
            with self.assertRaises(ValueError):self.prepare({**self.receipt,key:value})
        self.assertEqual(self.fixture.state(),self.previous)

    def test_does_not_create_unbounded_revision_four(self):
        self.prepare()
        with self.assertRaises(ValueError):self.prepare({**self.receipt,'decision_task':'another'})
