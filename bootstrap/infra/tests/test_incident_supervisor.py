import sys
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import incident_supervisor as supervisor
import delivery_gate


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE tasks(id TEXT, title TEXT, assignee TEXT, status TEXT,
          workspace_kind TEXT, completed_at INTEGER, last_heartbeat_at INTEGER,
          workspace_path TEXT, branch_name TEXT);
        CREATE TABLE task_events(id INTEGER,task_id TEXT,kind TEXT,payload TEXT);
        CREATE TABLE task_links(parent_id TEXT,child_id TEXT);
        CREATE TABLE task_comments(id INTEGER,task_id TEXT,author TEXT,body TEXT,created_at INTEGER);
        INSERT INTO tasks VALUES('t_abcd1234','GOVERNANCE','techlead','blocked','worktree',NULL,NULL,'.','branch');
        INSERT INTO task_events VALUES(1,'t_abcd1234','blocked','{"reason":"permission"}');
        ''')
        self.addCleanup(self.db.close)
        self.calls = []

    def cli(self, config, *args):
        self.calls.append(args)
        if args[0] == 'create':
            self.db.execute("INSERT INTO tasks(id,title,assignee,status) VALUES('t_inc','INCIDENT-t_abcd1234','cto','ready')")
            return '{"id":"t_inc"}'
        return ''

    def test_timeout_keeps_technical_decision_with_cto(self):
        state = {}
        with patch.object(supervisor, 'cli', self.cli):
            first = supervisor.tick(self.db, {}, state, 10000, lambda *_: None)
            supervisor.tick(self.db, {}, state, 10001, lambda *_: None)
            last = supervisor.tick(self.db, {}, state, 11801, lambda *_: None)
        self.assertEqual(sum(c[0] == 'create' for c in self.calls), 1)
        self.assertTrue(first)
        self.assertIn('CEO', last[-1])
        self.assertEqual(state['handoff_incidents']['t_abcd1234']['phase'], 'technical_attention')
        self.assertFalse(any('ESCALADO_AO_CEO' in str(c) for c in self.calls))

    def test_recurrence_reuses_incident(self):
        state = {}
        with patch.object(supervisor, 'cli', self.cli):
            supervisor.tick(self.db, {}, state, 10000, lambda *_: None)
            self.db.execute("UPDATE tasks SET status='running',last_heartbeat_at=10001 WHERE id='t_abcd1234'")
            supervisor.tick(self.db, {}, state, 10100, lambda *_: None)
            self.db.execute("UPDATE tasks SET status='blocked' WHERE id='t_abcd1234'")
            supervisor.tick(self.db, {}, state, 10200, lambda *_: None)
        self.assertEqual(sum(c[0] == 'create' for c in self.calls), 1)
        self.assertNotEqual(state['handoff_incidents']['t_abcd1234']['phase'], 'resolved')

    def test_done_without_merge_does_not_resolve(self):
        state = {}
        with patch.object(supervisor, 'cli', self.cli):
            supervisor.tick(self.db, {}, state, 10000, lambda *_: 'PR open')
            self.db.execute("UPDATE tasks SET status='done' WHERE id='t_abcd1234'")
            supervisor.tick(self.db, {}, state, 10100, lambda *_: 'PR open')
        self.assertNotEqual(state['handoff_incidents']['t_abcd1234']['phase'], 'resolved')

    def test_fresh_heartbeat_after_resume_is_not_resolution(self):
        state = {}
        with patch.object(supervisor, 'cli', self.cli):
            supervisor.tick(self.db, {}, state, 10000, lambda *_: None)
            self.db.execute("UPDATE tasks SET status='running',last_heartbeat_at=10001 WHERE id='t_abcd1234'")
            supervisor.tick(self.db, {}, state, 10100, lambda *_: None)
        self.assertEqual(state['handoff_incidents']['t_abcd1234']['phase'], 'monitoring_recovery')
        self.assertTrue(any(c[0] == 'schedule' for c in self.calls))

    def test_dashboard_response_resumes_only_incident_once(self):
        state = {}
        with patch.object(supervisor, 'cli', self.cli):
            supervisor.tick(self.db, {}, state, 10000, lambda *_: None)
            self.db.execute("UPDATE tasks SET status='blocked' WHERE id='t_inc'")
            self.db.execute("INSERT INTO task_comments VALUES(1,'t_inc','dashboard','APROVO',10010)")
            supervisor.tick(self.db, {}, state, 10020, lambda *_: None)
            supervisor.tick(self.db, {}, state, 10021, lambda *_: None)
        unblocks = [c for c in self.calls if c[0] == 'unblock']
        self.assertEqual(unblocks, [('unblock', 't_inc')])

    def test_open_pr_blocks_delivery_completion(self):
        def fake(path, *args):
            if args[1] == 'rev-parse': return 'abc'
            if args[1] == 'branch': return 'branch'
            if args[1] == 'status': return ''
            return '[]'
        with patch.object(delivery_gate, 'run', fake), patch.object(delivery_gate, 'active_release', return_value={'branch':'release/v0.1'}):
            self.assertIn('no merged PR', delivery_gate.check_delivery(self.db, 't_abcd1234'))

    def test_incident_cannot_complete_while_source_blocked(self):
        self.db.execute("INSERT INTO tasks(id,title,workspace_kind) VALUES('t_inc','INCIDENT-t_abcd1234','scratch')")
        self.assertIn('not resumed', delivery_gate.check_delivery(self.db, 't_inc'))


if __name__ == '__main__':
    unittest.main()
