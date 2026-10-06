import copy
import unittest
from broker import c10_micro_recovery as micro,c10_event_author as author,c10_event_plan as event,c10_status_admission as status
import test_c10_event_plan as fixtures


class MicroRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.EventPlanTests();fixture.setUp()
        state=event.prepare_fixed_facts(fixture.fixed_state(),fixture.output,fixture.trace)
        state=event.assess(state,fixture.choice_report(state,'resolveNewest'))
        state=author.prepare({'author':'author','cto':'cto'},state,48)
        state.update(stage='blocked',category='unchanged_functional_driver',author_task='failed-comment-author')
        self.state=state
        self.proof=copy.deepcopy(state['staged']['driver_guard']['qualification'])
        self.proof['worker_image']='sha256:'+'9'*64
        self.proof['micro_drain']={'schema':'surgical-micro-drain-probe-v1','status':'passed',
            'uid':10000,'network':'none','model_calls':0,'delivery_approval':False,
            **{flag:True for flag in micro.FLAGS}}

    def test_new_execution_seed_preserves_query_lineage_and_exact_admission(self):
        state=micro.prepare({'author':'author','cto':'cto'},self.state,self.proof,48)
        cp=state['c10_checkpoints']
        self.assertEqual(cp['seed'],self.state['c10_checkpoints']['seed'])
        self.assertEqual(cp['execution_seed']['validation']['test_sha256'],'f'*64)
        self.assertNotEqual(cp['scope_id'],self.state['c10_checkpoints']['scope_id'])
        self.assertEqual(cp['micro_resolver'],'resolveNewest')
        self.assertTrue(micro.binding(state,cp['execution_seed']))
        state.update(stage='awaiting_author',wakeup_id='micro-wake')
        task={'id':'micro-author','agent_id':'author','issue_id':state['issue_id'],
            'wakeup_id':'micro-wake','handoff_note':micro.note(state)}
        grant=status.select({'author':'author'},state,task)
        self.assertEqual(grant['surgical']['expected_sha256'],'f'*64)
        self.assertEqual(grant['surgical']['drain_resolver'],'resolveNewest')
        with self.assertRaises(ValueError):status.select({'author':'author'},state,dict(task,wakeup_id='old'))
        with self.assertRaises(ValueError):micro.binding(state,cp['seed'])

    def test_no_replay_self_review_small_reserve_or_unqualified_worker(self):
        cfg={'author':'author','cto':'cto'}
        with self.assertRaises(ValueError):micro.prepare(cfg,self.state,self.proof,47)
        with self.assertRaises(ValueError):micro.prepare({'author':'author','cto':'author'},self.state,self.proof,48)
        wrong=copy.deepcopy(self.proof);wrong['micro_drain']['proxy_marker_schema_preserved']=False
        with self.assertRaises(ValueError):micro.prepare(cfg,self.state,wrong,48)
        state=micro.prepare(cfg,self.state,self.proof,48)
        with self.assertRaises(ValueError):micro.prepare(cfg,state,self.proof,48)
