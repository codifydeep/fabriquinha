import json
import unittest
from unittest.mock import patch

import start_eval


class ModelBudgetTests(unittest.TestCase):
    def test_readonly_budget_inspection_does_not_authorize_dispatch(self):
        receipt = {'calls': 1162, 'max_calls': 1184, 'remaining': 22}
        with patch.object(start_eval.subprocess, 'check_output', return_value=json.dumps(receipt)):
            self.assertEqual(start_eval.read_model_budget(), receipt)
            with self.assertRaisesRegex(ValueError, 'model budget too low'):
                start_eval.check_model_budget()

    def test_release_requires_headroom_before_dispatch(self):
        with patch.object(start_eval.subprocess, 'check_output',
                          return_value=json.dumps({'calls': 33, 'max_calls': 64,
                                                   'remaining': 31})):
            with self.assertRaisesRegex(ValueError, 'model budget too low'):
                start_eval.check_model_budget()

    def test_sufficient_budget_is_reported(self):
        receipt = {'calls': 10, 'max_calls': 64, 'remaining': 54}
        with patch.object(start_eval.subprocess, 'check_output',
                          return_value=json.dumps(receipt)):
            self.assertEqual(start_eval.check_model_budget(), receipt)


if __name__ == '__main__':
    unittest.main()
