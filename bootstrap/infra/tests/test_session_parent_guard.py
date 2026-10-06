import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session_parent_guard import ensure_session_parent


class SessionParentTests(unittest.TestCase):
    def test_missing_parent_repaired_from_own_routing_entry(self):
        rows = set()
        db = SimpleNamespace(get_session=lambda sid: sid if sid in rows else None)
        entry = SimpleNamespace(session_id='s1', session_key='key1', origin=object(), display_name='group')
        store = SimpleNamespace(_lock=threading.RLock(), _entries={'key1': entry},
            _db_for_key=lambda key: db,
            _record_gateway_session_peer=lambda sid, *args, **kwargs: rows.add(sid))
        ensure_session_parent(store, 's1', db)
        self.assertIn('s1', rows)
        ensure_session_parent(store, 's1', db)
        self.assertEqual(rows, {'s1'})

    def test_unknown_owner_never_creates_synthetic_parent(self):
        db = SimpleNamespace(get_session=lambda sid: None)
        store = SimpleNamespace(_lock=threading.RLock(), _entries={})
        with self.assertRaises(RuntimeError):
            ensure_session_parent(store, 'missing', db)

    def test_other_profile_is_rejected(self):
        db = SimpleNamespace(get_session=lambda sid: None)
        entry = SimpleNamespace(session_id='s1', session_key='key1', origin=object())
        store = SimpleNamespace(_lock=threading.RLock(), _entries={'key1': entry}, _db_for_key=lambda key: object())
        with self.assertRaises(RuntimeError):
            ensure_session_parent(store, 's1', db)
