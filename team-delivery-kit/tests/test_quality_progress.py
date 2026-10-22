"""Persistent reconciliation tests with fixture native authority, not delivery."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from broker import quality_progress as progress
from broker import quality_red_capture as capture
from broker import validation_job
import test_quality_red_capture as fixtures


class QualityProgressTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.QualityRedCaptureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        self.b = fixture.b
        self.task = fixture.task
        self.b.QUALITY_V2_ENABLED = True
        with self.b.db() as con:
            con.execute('DELETE FROM controller_maintenance')
            progress.initialize(con)

    def observe(self):
        return progress.tick(self.b)['observed']

    def captured(self):
        with patch.object(capture.validation_job, 'run', side_effect=self.f.job):
            return capture.observe(self.b, self.task)

    def test_actual_capture_packet_is_durable_and_never_an_approval(self):
        state = self.captured()
        with patch.object(progress.snapshot, 'advance', return_value=state) as advance:
            result = self.observe()
            self.assertEqual(result[0]['stage'], 'review_ready')
            advance.assert_called_once_with(self.b, self.task)
        identity, saved = progress.load(self.b, self.task)
        packet = saved['packet']
        self.assertEqual(packet['red_sha256'], progress.quality.digest(state['red']))
        self.assertEqual(packet['frozen_test_candidates'], state['red']['tests'])
        self.assertEqual(packet['reviewer'], self.f.f.reviewer)
        self.assertFalse(packet['tests_approved'])
        self.assertFalse(packet['execution_authorized'])
        self.assertFalse(saved['delivery_approval'])
        restarted = SimpleNamespace(**vars(self.b))
        with patch.object(progress.snapshot, 'advance', side_effect=AssertionError('no replay')):
            self.assertEqual(progress.tick(restarted)['observed'], [])
            self.assertEqual(progress.advance(restarted, self.task), saved)

    def test_worker_returned_red_without_controller_capture_is_blocked(self):
        fake = dict(stage='awaiting_independent_test_review', owner=self.f.f.reviewer,
            red=self.f.red_report()['red'])
        with patch.object(progress.snapshot, 'advance', return_value=fake):
            self.assertEqual(self.observe()[0]['stage'], 'technical_blocked')
        with patch.object(progress.snapshot, 'advance', side_effect=AssertionError('no identical retry')):
            self.assertEqual(self.observe(), [])

    def test_pending_reobserves_same_source_without_minting_capabilities(self):
        with patch.object(progress.snapshot, 'advance', side_effect=validation_job.Pending('same job')) as advance:
            self.assertEqual(self.observe()[0]['stage'], 'observing')
            self.assertEqual(self.observe()[0]['stage'], 'observing')
            self.assertEqual(advance.call_args_list[0], advance.call_args_list[1])
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM grants').fetchone()[0], 1)
        state = self.captured()
        with patch.object(progress.snapshot, 'advance', return_value=state):
            self.assertEqual(self.observe()[0]['stage'], 'review_ready')

    def test_native_completion_lag_is_observed_without_copy_or_author_retry(self):
        self.f.native['status'] = 'running'
        with patch.object(progress.snapshot, 'advance') as advance:
            for _ in range(3):
                self.assertEqual(self.observe()[0]['stage'], 'waiting_native_completion')
            advance.assert_not_called()
        self.assertIsNone(progress.load(self.b, self.task))
        self.f.native['status'] = 'completed'
        with patch.object(progress.snapshot, 'advance', side_effect=validation_job.Pending('same job')):
            self.assertEqual(self.observe()[0]['stage'], 'observing')

    def test_sealed_maintenance_and_default_disabled_start_no_effects(self):
        self.b.QUALITY_V2_ENABLED = False
        self.assertEqual(progress.tick(self.b)['stage'], 'disabled')
        self.b.QUALITY_V2_ENABLED = True
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                ('operation', 'sealed', json.dumps(dict(stage='sealed'))))
        with patch.object(progress.snapshot, 'advance') as advance:
            self.assertEqual(progress.tick(self.b)['stage'], 'maintenance')
            advance.assert_not_called()

    def test_two_identical_external_failures_block_with_technical_owner(self):
        with patch.object(progress.snapshot, 'advance', side_effect=TimeoutError('private data must not be copied')) as advance:
            self.assertEqual(self.observe()[0]['stage'], 'observing')
            self.assertEqual(self.observe()[0]['stage'], 'technical_blocked')
            self.assertEqual(self.observe(), [])
            self.assertEqual(advance.call_count, 2)
        _, saved = progress.load(self.b, self.task)
        self.assertEqual(saved['owner'], self.f.lead)
        self.assertFalse(saved['incident']['automatic_retry'])
        self.assertNotIn('private data', json.dumps(saved))

    def test_rejected_discovery_cannot_starve_other_sources_and_is_bounded(self):
        others = ['40000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000004']
        with self.b.db() as con:
            for i, task in enumerate(others):
                request = 'other-' + str(i)
                con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                    (request, task, self.f.f.author, 'other-scope', self.f.issue))
                con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)', (request, task, 1, 'implementation', 1, 0))
                con.execute('INSERT INTO leases VALUES(?,?)', (request, 'closed'))
                con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
                    (request, task, self.f.plan['run_id'], 'tests_only_v2', progress.quality.digest(self.f.plan)))
        def fail(b, task):
            if task == self.task:
                raise ValueError('rejected source')
            return dict(stage='waiting_native_completion', owner=self.f.f.author)
        with patch.object(progress, 'advance', side_effect=fail):
            seen = []
            for _ in range(4):
                seen.extend(progress.tick(self.b, limit=1)['observed'])
        self.assertTrue(set(others) <= {row['task_id'] for row in seen})
        self.assertEqual(seen[-1]['stage'], 'authority_blocked')
        self.assertNotIn(self.task, progress.candidates(self.b))

    def test_hash_tampering_is_not_reconciled_as_success(self):
        with patch.object(progress.snapshot, 'advance', side_effect=validation_job.Pending('same job')):
            self.observe()
        with self.b.db() as con:
            con.execute("UPDATE quality_progress SET state='{}'")
        with patch.object(progress.snapshot, 'advance') as advance:
            with self.assertRaises(ValueError):
                progress.tick(self.b)
            advance.assert_not_called()

    def test_original_os_lock_is_not_stolen_and_releases_without_timestamp_guessing(self):
        with progress.exclusive(self.b):
            with self.assertRaises(validation_job.Pending):
                progress.tick(self.b)
        self.f.native['status'] = 'running'
        self.assertEqual(self.observe()[0]['stage'], 'waiting_native_completion')

    def test_limits_and_terminal_native_failure_never_launch_copy(self):
        for value in (0, 3, True):
            with self.assertRaises(ValueError):
                progress.tick(self.b, limit=value)
        self.f.native['status'] = 'failed'
        with patch.object(progress.snapshot, 'advance') as advance:
            self.assertEqual(self.observe()[0]['stage'], 'authority_rejected')
            self.assertEqual(self.observe()[0]['stage'], 'authority_blocked')
            advance.assert_not_called()


if __name__ == '__main__':
    unittest.main()
