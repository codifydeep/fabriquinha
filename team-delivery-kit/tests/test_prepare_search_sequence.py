import json
from pathlib import Path
import unittest

from prepare_search_sequence import derive
from dependent_sequence import protection_transition_allowed


class SearchSequenceTests(unittest.TestCase):
    def test_contracts_preserve_all_baseline_and_predecessor_tests(self):
        template = json.loads((Path(__file__).resolve().parents[1] /
                              'projects/descartavel2-sort-1.contract.json').read_text())
        existing = template['files']
        result = derive(existing, template)
        api = result['descartavel2-search-1-api.contract.json']
        ui = result['descartavel2-search-1-ui.contract.json']
        self.assertTrue(set(template['test_files']) <= set(api['protected_files']))
        self.assertTrue(set(api['test_files']) <= set(ui['protected_files']))
        self.assertTrue(protection_transition_allowed(api, ui))
        self.assertIn('app/server.py', ui['protected_files'])
        self.assertIn('app/static/app.js', api['protected_files'])
        with self.assertRaisesRegex(ValueError, 'fresh'):
            derive(existing + ['tests/test_feedback_search_api.py'], template)
        with self.assertRaisesRegex(ValueError, 'sort baseline'):
            derive([p for p in existing if p != 'tests/test_feedback_sort_client.py'], template)

