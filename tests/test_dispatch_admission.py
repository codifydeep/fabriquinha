"""Pre-claim adapter preserves native guards and scopes provider holds."""
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

class Admission(unittest.TestCase):
    def test_provider_wait_preserves_native_guards_and_other_connections(self):
        from fabriquinha.runtime import provider_claim_guard
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('CREATE TABLE tasks (id TEXT, body TEXT)')
        for ident,kind in [('model','tests'),('fixed','integration')]:
            conn.execute('INSERT INTO tasks VALUES (?,?)',(ident,json.dumps({'kind':kind})))
        original=lambda connection,task,**kw:'active_pr' if task=='protected' else None
        dispatch=SimpleNamespace(check_respawn_guard=original)
        other=object()
        with self.assertRaisesRegex(RuntimeError,'interrupt'):
            with provider_claim_guard(dispatch,conn,ready=False):
                self.assertEqual(dispatch.check_respawn_guard(conn,'model',lane='review'),'provider_unavailable')
                self.assertIsNone(dispatch.check_respawn_guard(conn,'fixed',lane='ready'))
                self.assertEqual(dispatch.check_respawn_guard(conn,'protected',lane='ready'),'active_pr')
                self.assertIsNone(dispatch.check_respawn_guard(other,'model',lane='ready'))
                raise RuntimeError('interrupt')
        self.assertIs(dispatch.check_respawn_guard,original)
        with provider_claim_guard(dispatch,conn,ready=True):
            self.assertIs(dispatch.check_respawn_guard,original)
