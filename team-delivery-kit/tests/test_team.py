import unittest
from register_team import MODEL, validate_existing
from set_eval_model import planned_agents, PREVIOUS


class PilotTests(unittest.TestCase):
    def test_model_migration_is_limited_to_registered_eval_identities(self):
        agents = [{'id': str(i), 'name': 'eval_' + str(i), 'model': PREVIOUS}
                  for i in range(4)]
        team = {'agents': {'a': '0', 'b': '1', 'c': '2'}}
        native = {'agent_id': '3'}
        self.assertEqual(len(planned_agents(agents, team, native)), 4)
        with self.assertRaises(ValueError):
            planned_agents([{**agents[0], 'name': 'production'}, *agents[1:]], team, native)
        with self.assertRaises(ValueError):
            planned_agents([{**agents[0], 'model': 'unknown'}, *agents[1:]], team, native)

    def test_matching_registration(self):
        validate_existing(dict(runtime_id='r', model=MODEL,
                               max_concurrent_tasks=1, visibility='workspace'), 'r')

    def test_each_permission_or_model_drift_is_rejected(self):
        valid = dict(runtime_id='r', model=MODEL,
                     max_concurrent_tasks=1, visibility='workspace')
        for key, value in dict(runtime_id='other', model='other',
                               max_concurrent_tasks=2, visibility='public').items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_existing({**valid, key: value}, 'r')
