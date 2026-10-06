import json
import unittest
from unittest.mock import patch

from materialize_plan import card_description, ensure_card, plan_from_ledger


class MaterializePlanTests(unittest.TestCase):
    def setUp(self):
        self.card = {'id': 'C1', 'title': 'API', 'owner': 'backend_data',
                     'depends_on': [], 'acceptance': ['API test passes'],
                     'files': ['app/server.js'], 'test_command': ['node', '--test']}

    def test_card_is_blocked_and_unassigned(self):
        with patch('materialize_plan.cli', return_value={'id': 'abc', 'status': 'blocked'}) as cli:
            self.assertEqual(ensure_card(self.card, 'a' * 64, [])['id'], 'abc')
        args = cli.call_args.args
        self.assertEqual(args[-2:], ('--status', 'blocked'))
        self.assertIn('NOT READY FOR EXECUTION', args[4])

    def test_reuse_rejects_early_assignment(self):
        description = card_description(self.card, 'a' * 64)
        item = {'id': 'abc', 'title': 'PILOT-FEEDBACK-BOARD — C1 — API',
                'description': description, 'status': 'blocked', 'assignee_id': 'worker'}
        with self.assertRaisesRegex(ValueError, 'premature dispatch'):
            ensure_card(self.card, 'a' * 64, [item])

    def test_incomplete_or_unvalidated_plan_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not ready'):
            plan_from_ledger({'stage': 'working_techlead'})
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            plan_from_ledger({'stage': 'plan_ready', 'outputs': {}})


if __name__ == '__main__':
    unittest.main()
