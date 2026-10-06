import unittest

from review_wakeup import ensure_review_wakeup


class ReviewWakeupTests(unittest.TestCase):
    def test_spent_one_shot_is_replaced_once(self):
        wakeups = [{'agent_id': 'reviewer', 'event_types': ['task.completed'],
                    'filter_agent_id': 'author', 'filter_task_id': None,
                    'enabled': False, 'instruction': 'review'}]
        created = []

        def cli(*args):
            if args[:2] == ('wakeup', 'list'):
                return wakeups
            created.append(args)
            new = {**wakeups[0], 'enabled': True, 'id': 'new'}
            wakeups.append(new)
            return new

        self.assertEqual(ensure_review_wakeup(cli, 'issue', 'author', 'reviewer', 'review')['id'], 'new')
        self.assertEqual(ensure_review_wakeup(cli, 'issue', 'author', 'reviewer', 'review')['id'], 'new')
        self.assertEqual(len(created), 1)

    def test_active_instruction_drift_fails_closed(self):
        def cli(*args):
            return [{'agent_id': 'reviewer', 'event_types': ['task.completed'],
                     'filter_agent_id': 'author', 'filter_task_id': None,
                     'enabled': True, 'instruction': 'old'}]

        with self.assertRaisesRegex(ValueError, 'instruction drift'):
            ensure_review_wakeup(cli, 'issue', 'author', 'reviewer', 'new')


if __name__ == '__main__':
    unittest.main()
