import copy,json,unittest
import test_incremental_controls_revision as fixtures
from broker import incremental_checkpoints as ledger
from broker.incremental_negative_revision import validate_spike


class NegativeRevisionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ControlsRevisionTests();f.setUp();self.addCleanup(f.doCleanups);self.con=f.con
        state=f.prepare();u=state['units']['U1'];u.update(stage='awaiting_green',binding={'issue_id':'revision5'},red='1'*64,test_review='2'*64)
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),));self.before=copy.deepcopy(state)
        self.r=dict(operation='cto_negative_spike_revision_v1',source_task='source',unit='U1',parent_issue='revision5',
            decision_task='native-cto',cto='cto',proposal_sha256='a'*64,reason='Fix two helper defects',experiment_sha256='9'*64,
            fixture_volume='owned-fixture',negative_spike_sha256='3'*64,original_red='1'*64,rejected_manifest_sha256='4'*64)

    def prepare(self,r=None):
        r=self.r if r is None else r
        return ledger.prepare_negative_spike_revision(self.con,'source',ledger.digest(r),lambda _:r)

    def test_exact_revision_preserves_history_baseline_and_dependencies(self):
        state=self.prepare();u=state['units']['U1'];self.assertEqual(u['revision'],6)
        self.assertEqual(state,self.prepare());self.assertFalse(state['execution_authorized'])
        self.assertEqual(u['history'][-1]['test_review'],'2'*64)
        for key in ['base_manifest_sha256','baseline_test_sha256','prior_test_count']:self.assertEqual(u[key],self.before['units']['U1'][key])
        self.assertEqual(state['units']['U2'],self.before['units']['U2'])
        for key in ['red','test_review','green','binding']:self.assertNotIn(key,u)

    def test_unrelated_or_unapproved_sponsorship_does_not_reset(self):
        for key,value in [('original_red','0'*64),('parent_issue','other'),('cto','author'),
                          ('negative_spike_sha256','invalid'),('experiment_sha256','0'*64)]:
            with self.assertRaises(ValueError):self.prepare({**self.r,key:value})
        self.assertEqual(ledger.status(self.con,'source'),self.before)


class SpikeValidationTests(unittest.TestCase):
    def test_exact_causal_evidence_required_not_a_green_receipt(self):
        path='tests/test_feedback_search_client.py';red={'red':{'test_sha256':{path:'a'*64}}}
        positive='test_native_search_input_named_search_feedback_is_outside_the_form'
        tests={positive:True,**{'negative'+str(i):True for i in range(5)}}
        base={'original':{'inside_control':{'canonical_match':False}},'parser_only':{'inside_control':{'accepted':True}},
              'both':{'inside_control':{'accepted':False,'canonical_match':True,'rejected_by_predicate':True},'test_results':tests}}
        proof={'operation':'frozen_negative_control_spike_v1','inputs_unchanged':True,'in_memory_hypotheses_only':True,
               'delivery_approval':False,'valid_red_green_receipt':False,'input_sha256':{'red':{path:'a'*64}},
               'reports':{'red':copy.deepcopy(base),'candidate':copy.deepcopy(base)}}
        proof['reports']['red']['both']['test_results'][positive]=False
        self.assertIsNone(validate_spike(proof,red))
        for key,value in [('delivery_approval',True),('inputs_unchanged',False),('valid_red_green_receipt',True)]:
            with self.assertRaises(ValueError):validate_spike({**proof,key:value},red)
        broken=copy.deepcopy(proof);broken['reports']['red']['both']['test_results'][positive]=True
        with self.assertRaises(ValueError):validate_spike(broken,red)
