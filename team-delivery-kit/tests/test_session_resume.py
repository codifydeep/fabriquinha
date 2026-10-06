import sqlite3
import unittest

from broker.session_resume import prior_session


class SessionResumeTests(unittest.TestCase):
    def test_same_task_can_resume_but_phase_handoff_starts_fresh(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.executescript('CREATE TABLE acp_sessions(scope TEXT,session_id TEXT); '
                          'CREATE TABLE acp_events(request_id TEXT,session_id TEXT); '
                          'CREATE TABLE native_bindings(request_id TEXT,scope TEXT,task_id TEXT);')
        con.execute('INSERT INTO acp_sessions VALUES (?,?)', ('workspace', 'tests-history'))
        con.execute('INSERT INTO acp_events VALUES (?,?)', ('test-request', 'tests-history'))
        con.execute('INSERT INTO native_bindings VALUES (?,?,?)', ('test-request', 'workspace', 'tests-task'))
        self.assertEqual(prior_session(con, 'workspace', 'tests-task'), 'tests-history')
        self.assertIsNone(prior_session(con, 'workspace', 'implementation-task'))
        self.assertIsNone(prior_session(con, 'other-workspace', 'tests-task'))
        con.execute('INSERT INTO acp_sessions VALUES (?,?)', ('workspace', 'implementation-history'))
        con.execute('INSERT INTO acp_events VALUES (?,?)', ('implementation-request', 'implementation-history'))
        con.execute('INSERT INTO native_bindings VALUES (?,?,?)', ('implementation-request', 'workspace', 'implementation-task'))
        self.assertEqual(prior_session(con, 'workspace', 'implementation-task'), 'implementation-history')
        self.assertEqual(prior_session(con, 'workspace', 'tests-task'), 'tests-history')
