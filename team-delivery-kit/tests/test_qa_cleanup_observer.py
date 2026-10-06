import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from broker import qa_cleanup_observer as observer


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'state.sqlite'
        self.config = dict(owner='owner', resources=[['container', 'exact']],
            failed_execution={'request': {'source_sha': 'a'*40}},
            failed_execution_sha256='b'*64, failed_browser_sha256='c'*64)
        self.state = dict(stage='observing', at=0, probes=0, errors=0, owner='devops',
                          next_action='Observe exact resources; never repeat uncertain deletion')
        self.b = SimpleNamespace(db=self.db, docker=Mock(side_effect=[{'Version': 'ok'}, None]))
        with self.db() as con:
            observer.initialize(con)
            con.execute('INSERT INTO qa_cleanup_observations VALUES(?,?,?,?)',
                        ('task', json.dumps(self.config), json.dumps(self.state), 0))

    @contextlib.contextmanager
    def db(self):
        con = sqlite3.connect(self.path); con.row_factory = sqlite3.Row
        try:
            with con: yield con
        finally: con.close()

    def test_absence_after_restart_is_read_only_idempotent_and_not_approval(self):
        result = observer.tick(self.b, now=1)
        self.assertEqual(result['stage'], 'cleanup_absence_confirmed')
        self.assertFalse(result['receipt']['release_homologated'])
        self.assertFalse(result['receipt']['tests_reexecuted'])
        self.assertFalse(result['receipt']['deletion_repeated'])
        observer.tick(self.b, now=1000)
        self.assertEqual(self.b.docker.call_count, 2)
        self.assertTrue(all(call.args[0]=='GET' for call in self.b.docker.call_args_list))

    def test_foreign_resource_is_retained_and_escalated(self):
        self.b.docker.side_effect = [{'Version': 'ok'}, {'Config': {'Labels': {}}}]
        result = observer.tick(self.b, now=1)
        self.assertEqual(result['stage'], 'blocked'); self.assertEqual(result['owner'], 'cto')
        self.assertTrue(all(call.args[0]=='GET' for call in self.b.docker.call_args_list))

    def test_two_observation_errors_stop_retries_across_process_restarts(self):
        self.b.docker.side_effect = TimeoutError()
        first = observer.tick(self.b, now=1)
        self.assertEqual(first['stage'], 'observing')
        # A fresh adapter / DB connection sees the same persisted retry count.
        restarted = SimpleNamespace(db=self.db, docker=Mock(side_effect=TimeoutError()))
        second = observer.tick(restarted, now=60)
        self.assertEqual(second['stage'], 'blocked'); self.assertEqual(second['errors'], 2)
        observer.tick(restarted, now=3600); self.assertEqual(restarted.docker.call_count, 1)

    def test_remaining_owned_resource_alerts_then_escalates_without_delete(self):
        self.b.docker.side_effect = None
        self.b.docker.return_value = {'Version': 'ok', 'Config': {'Labels': {'delivery-kit.browser-qa': 'owner'}}}
        first = observer.tick(self.b, now=600)
        self.assertTrue(first['alerted']); self.assertEqual(first['stage'], 'observing')
        second = observer.tick(self.b, now=1800)
        self.assertEqual(second['stage'], 'blocked'); self.assertEqual(second['owner'], 'techlead')

    def test_unhealthy_docker_never_proves_absence(self):
        self.b.docker.side_effect = None; self.b.docker.return_value = None
        result = observer.tick(self.b, now=1)
        self.assertEqual(result['stage'], 'observing'); self.assertNotIn('receipt', result)

    def test_enrollment_rejects_arbitrary_or_functionally_failed_evidence(self):
        self.b.PREFIX = 'delivery-kit-port2'
        for reason in ('functional tests failed', 'cleanup succeeded'):
            packet = dict(failed_execution={'stage': 'blocked', 'reason': reason},
                          failed_browser={}, failed_execution_sha256='a'*64,
                          failed_browser_sha256='b'*64)
            with self.assertRaises(ValueError): observer.register(self.b, packet)
        self.b.docker.assert_not_called()
