import copy
import json
import unittest
from broker.dependency_inventory_recovery import prepare


class DependencyInventoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.failure = dict(category='executed_test_failure', source_task='source', volume='frozen',
            output_sha256='a' * 64, tests_executed=3, failures=[dict(kind='ERROR', qualified_name='tests.C.test_get')],
            diagnostic_read_files=['app/server.py'], missing_module_attributes=[dict(module='app.db', attribute='get_item')])
        self.data = dict(validation_failure=self.failure, phase_evidence=dict(red_manifest='red', independent_test_review='approved'),
            attempts=2, instruction='old', recipient_task='cto-old')
        self.row = dict(source_task='source', stage='technical_decision_required', data=json.dumps(self.data))
        self.enriched = dict(self.failure, diagnostic_read_files=['app/db.py', 'app/server.py'],
            diagnostic_source_hashes={'app/db.py': 'b' * 64})

    def test_same_execution_context_expands_once_without_approval_or_counter_reset(self):
        result = prepare(self.row, self.enriched)
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(result['phase_evidence'], self.data['phase_evidence'])
        self.assertEqual(result['diagnostic_inventory_recovery']['previous_diagnosis'], self.data)
        self.assertFalse(result['diagnostic_inventory_recovery']['delivery_approval'])
        self.assertFalse(result['diagnostic_inventory_recovery']['author_restarted'])
        self.assertNotIn('recipient_task', result)
        with self.assertRaises(ValueError):
            prepare(dict(self.row, data=json.dumps(result)), self.enriched)

    def test_missing_new_evidence_or_different_delivery_is_rejected(self):
        for failure in (self.failure, dict(self.enriched, output_sha256='c' * 64),
                        dict(self.enriched, source_task='other'), dict(self.enriched, volume='other')):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                prepare(self.row, failure)
        self.assertEqual(json.loads(self.row['data']), self.data)
