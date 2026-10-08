import contextlib
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import controller_maintenance as m


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        self.con.execute('CREATE TABLE grants(request_id TEXT,used INTEGER,deadline REAL)')
        @contextlib.contextmanager
        def db():
            with self.con: yield self.con
        self.b = SimpleNamespace(db=db, LOCK=threading.RLock(), PREFIX='delivery-kit-test')
        self.operation = '12345678-1234-1234-1234-123456789abc'
        m._cycle_ids.clear()
        self.inventory = patch.object(m, 'native_active', return_value=[])
        self.inventory.start()

    def tearDown(self):
        self.inventory.stop(); self.con.close(); m._cycle_ids.clear()

    def test_drain_admits_existing_tasks_but_seal_blocks_new_grants(self):
        m.begin(self.b, self.operation)
        self.assertFalse(m.begin_cycle(self.b))
        m.require_admission(self.con)
        self.assertTrue(m.seal(self.b, self.operation)['drained'])
        with self.assertRaises(ValueError): m.require_admission(self.con)
        # Simulate a new module process: durable maintenance still refuses work.
        m._cycle_ids.clear()
        self.assertFalse(m.begin_cycle(self.b))
        m.release(self.b, self.operation)
        m.require_admission(self.con)
        self.assertTrue(m.begin_cycle(self.b)); m.end_cycle(self.b)

    def test_queued_native_tasks_prevent_sealing_without_leases(self):
        m.begin(self.b, self.operation)
        with patch.object(m, 'native_active', return_value=['queued']):
            result = m.seal(self.b, self.operation)
        self.assertFalse(result['drained']); self.assertEqual(result['native_active'], 1)

    def test_existing_cycle_and_closing_lease_must_drain(self):
        self.assertTrue(m.begin_cycle(self.b))
        m.begin(self.b, self.operation)
        self.assertFalse(m.seal(self.b, self.operation)['drained'])
        m.end_cycle(self.b)
        self.con.execute("INSERT INTO leases VALUES ('lease','closing')")
        self.assertFalse(m.seal(self.b, self.operation)['drained'])

    def test_exact_owner_identity_and_no_reuse_or_approval(self):
        before = m.begin(self.b, self.operation)
        self.assertEqual(m.begin(self.b, self.operation), before)
        self.assertFalse(before['delivery_approval']); self.assertFalse(before['grants_replayed'])
        other = '22345678-1234-1234-1234-123456789abc'
        with self.assertRaises(ValueError): m.begin(self.b, other)
        with self.assertRaises(ValueError): m.release(self.b, self.operation)
        m.seal(self.b, self.operation)
        with self.assertRaises(ValueError): m.release(self.b, other)
        m.release(self.b, self.operation)
        with self.assertRaises(ValueError): m.begin(self.b, self.operation)

    def test_inventory_failure_never_seals(self):
        m.begin(self.b, self.operation)
        with patch.object(m, 'native_active', side_effect=TimeoutError), self.assertRaises(TimeoutError):
            m.seal(self.b, self.operation)
        self.assertEqual(m.current(self.con)['stage'], 'draining')

    def test_operator_process_cannot_miss_an_active_durable_cycle(self):
        self.assertTrue(m.begin_cycle(self.b))
        m.begin(self.b, self.operation)
        # Another operator process has no Python-local cycle IDs. The durable
        # ledger must still block sealing, including after an uncertain crash.
        saved = m._cycle_ids.copy()
        m._cycle_ids.clear()
        result = m.seal(self.b, self.operation)
        self.assertFalse(result['drained']); self.assertEqual(result['active_cycles'], 1)
        m._cycle_ids.update(saved)
        m.end_cycle(self.b)
        self.assertTrue(m.seal(self.b, self.operation)['drained'])

    def test_consumed_grant_before_lease_creation_prevents_sealing(self):
        import time
        m.begin(self.b, self.operation)
        self.con.execute('INSERT INTO grants VALUES(?,?,?)', ('launch', 1, time.time()+60))
        result = m.seal(self.b, self.operation)
        self.assertFalse(result['drained']); self.assertEqual(result['launching_grants'], 1)
