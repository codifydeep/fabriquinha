import copy
import unittest
from planning_intake import cto_context_replan


class CTOContextReplanTests(unittest.TestCase):
    def state(self):
        return {'stage':'blocked','active':'techlead','owner':'techlead',
            'category':'ValueError:planning context exceeds issue limit','retry_techlead':1,
            'outputs':{'product':{'proposal':{'business_questions':[]}},
                       'cto':{'task_id':'previous-cto','proposal':{'stack':'existing'}}},
            'issues':{'product':'p','cto':'c','techlead':'t'},'ceo_answer':{'answer':'Real answer'}}

    def test_technical_context_replan_preserves_prior_choices_and_human_answer(self):
        state=self.state();before=copy.deepcopy(state)
        result=cto_context_replan(state)
        self.assertEqual(state,before)
        self.assertEqual(result['active'],'cto')
        self.assertEqual(result['owner'],'cto')
        self.assertEqual(result['outputs'],{'product':before['outputs']['product']})
        self.assertEqual(result['prior_cto_context']['output'],before['outputs']['cto'])
        self.assertEqual(result['ceo_answer'],before['ceo_answer'])
        self.assertEqual(result['schema_cto'],1)
        self.assertEqual(result['retry_techlead'],1)

    def test_replan_is_one_shot_not_a_repeated_retry_or_permission_waiver(self):
        state=cto_context_replan(self.state())
        state.update(stage='blocked',active='techlead',category='ValueError:planning context exceeds issue limit')
        self.assertIsNone(cto_context_replan(state))
        self.assertNotIn('authorizes_merge',state)

    def test_other_blockers_and_business_questions_are_not_replanned(self):
        for category in ('ValueError:other','RuntimeError:planning agent task failed'):
            self.assertIsNone(cto_context_replan({**self.state(),'category':category}))
        self.assertIsNone(cto_context_replan({**self.state(),'stage':'blocked_awaiting_ceo'}))

    def test_resumed_status_tracks_actual_owner_and_archives_the_old_failure(self):
        from planning_intake import mark_working
        state=self.state();mark_working(state,'cto')
        self.assertEqual((state['stage'],state['active'],state['owner']),('working_cto','cto','cto'))
        self.assertNotIn('category',state)
        self.assertEqual(state['prior_planning_incidents'][0]['active'],'techlead')
        mark_working(state,'techlead')
        self.assertEqual(state['owner'],'techlead')
        self.assertEqual(len(state['prior_planning_incidents']),1)
