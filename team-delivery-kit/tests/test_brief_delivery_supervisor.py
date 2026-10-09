import json
from pathlib import Path
import tempfile
import unittest

from brief_delivery_supervisor import supervise, verify_registration
from unittest.mock import patch


class BriefSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'pipeline.json'
        self.steps = ['planning', 'materializing', 'compiling', 'executing']

    def test_post_delivery_memory_failure_is_separate_durable_and_not_replayed(self):
        from brief_delivery_supervisor import post_delivery_memory
        config={'name':'MEMORY-TEST','sha256':'a'*64}
        with patch('release_memory_pipeline.run',side_effect=ValueError('provenance missing')) as run:
            first=post_delivery_memory(config,Path(self.temp.name),'delivery-kit-one')
            second=post_delivery_memory(config,Path(self.temp.name),'delivery-kit-one')
            self.assertEqual(first,second);run.assert_called_once()
        self.assertEqual(first['owner'],'cto');self.assertFalse(first['delivery_approval'])
        self.assertEqual(first['stage'],'blocked')

    def test_all_steps_are_automatic_and_durable(self):
        calls = []
        def run(step):
            calls.append(step)
            self.assertEqual(json.loads(self.path.read_text())['active'], step)
            return 0
        self.assertEqual(supervise(self.path, 'a' * 64, run), 0)
        self.assertEqual(calls, self.steps)
        self.assertEqual(json.loads(self.path.read_text())['stage'], 'qualified')

    def test_restart_after_compilation_only_reconciles_execution(self):
        calls = []
        def crash(step):
            calls.append(step)
            if step == 'executing':
                raise OSError('operator process interrupted')
            return 0
        with self.assertRaises(OSError):
            supervise(self.path, 'a' * 64, crash)
        calls.clear()
        self.assertEqual(supervise(self.path, 'a' * 64, lambda step: calls.append(step) or 0), 0)
        self.assertEqual(calls, ['executing'])

    def test_failure_is_visible_and_not_blindly_retried(self):
        calls = []
        self.assertEqual(supervise(self.path, 'a' * 64, lambda step: calls.append(step) or 1), 1)
        ledger = json.loads(self.path.read_text())
        self.assertEqual(ledger['stage'], 'blocked')
        self.assertEqual(ledger['active'], 'planning')
        self.assertEqual(ledger['owner'], 'techlead')
        self.assertIn('next_action', ledger)
        self.assertEqual(supervise(self.path, 'a' * 64, lambda step: self.fail('blind retry')), 1)

    def test_input_drift_blocks_before_dispatch(self):
        supervise(self.path, 'a' * 64, lambda _: 1)
        with self.assertRaisesRegex(ValueError, 'identity'):
            supervise(self.path, 'b' * 64, lambda step: self.fail('dispatch'))

    def test_qualified_state_revalidates_delivery_not_replans(self):
        supervise(self.path, 'a' * 64, lambda _: 0)
        calls = []
        self.assertEqual(supervise(self.path, 'a' * 64, lambda s: calls.append(s) or 0), 0)
        self.assertEqual(calls, ['executing'])

    def test_malformed_progress_cannot_skip_controls(self):
        self.path.write_text(json.dumps({'identity': 'a' * 64, 'stage': 'working',
                                         'completed': ['compiling']}))
        with self.assertRaisesRegex(ValueError, 'progress'):
            supervise(self.path, 'a' * 64, lambda step: self.fail('dispatch'))

    def test_execution_incident_can_only_reconcile_through_existing_sequence(self):
        self.assertEqual(supervise(self.path, 'a' * 64, lambda step: 1 if step == 'executing' else 0), 1)
        calls = []
        self.assertEqual(supervise(self.path, 'a' * 64, lambda step: calls.append(step) or 1), 1)
        self.assertEqual(calls, ['executing'])
        self.assertEqual(json.loads(self.path.read_text())['stage'], 'blocked')
        self.assertEqual(supervise(self.path, 'a' * 64, lambda step: 0), 0)
        self.assertNotIn('category', json.loads(self.path.read_text()))

    def test_reconciliation_preserves_old_incident_without_reporting_it_as_current(self):
        supervise(self.path, 'a' * 64, lambda step: 1 if step == 'executing' else 0)
        def run(step):
            state = json.loads(self.path.read_text())
            self.assertEqual(state['stage'], 'working')
            self.assertNotIn('category', state)
            self.assertEqual(state['prior_incidents'][-1]['category'], 'brief_delivery_executing_not_qualified')
            self.assertEqual(state['prior_incidents'][-1]['status'], 'reconciliation_in_progress')
            return 1
        self.assertEqual(supervise(self.path, 'a' * 64, run), 1)
        self.assertEqual(json.loads(self.path.read_text())['category'], 'brief_delivery_executing_not_qualified')

    def test_failed_reconciliations_do_not_duplicate_same_incident_history(self):
        supervise(self.path, 'a' * 64, lambda step: 1 if step == 'executing' else 0)
        supervise(self.path, 'a' * 64, lambda step: 1)
        supervise(self.path, 'a' * 64, lambda step: 1)
        state = json.loads(self.path.read_text())
        self.assertEqual(len(state['prior_incidents']), 1)
        self.assertEqual(state['stage'], 'blocked')

    def test_symlink_ledger_is_rejected(self):
        target = self.path.parent / 'target.json'
        target.write_text('{}')
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            supervise(self.path, 'a' * 64, lambda step: self.fail('dispatch'))

    def test_service_registration_is_checked_before_first_ledger_exists(self):
        private = self.path.parent
        directory = private / 'host-service'
        directory.mkdir()
        config = {'name': 'NEW-1', 'sha256': 'a' * 64, 'path': private / 'approved.json'}
        path = directory / 'NEW-1.brief-input.json'
        path.write_text(json.dumps({'input_sha256': config['sha256'], 'configuration': str(config['path'])}))
        verify_registration(config, private)
        config['sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'drift'):
            verify_registration(config, private)
