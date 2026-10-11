import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from broker import controller_route_isolation as isolation
from test_test_first_handoffs import Broker

ISSUE='11111111-1111-4111-8111-111111111111'
OLD='22222222-2222-4222-8222-222222222222'
OP='33333333-3333-4333-8333-333333333333'


class RouteIsolationTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.b=Broker(Path(directory.name)/'db');self.b.PREFIX='delivery-kit-test'
        self.target=dict(enabled=True,contract='unchanged')
        self.old=dict(enabled=True,contract='historical')
        with self.b.db() as con:
            isolation.maintenance.initialize(con)
            con.execute('CREATE TABLE leases(status TEXT)')
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            con.executemany('INSERT INTO delivery_routes VALUES(?,?)',
                [(ISSUE,json.dumps(self.target)),(OLD,json.dumps(self.old))])
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                (OP,'sealed',json.dumps(dict(stage='sealed',operation_id=OP,namespace=self.b.PREFIX))))

    def apply(self):
        with patch.object(isolation.maintenance,'native_active',return_value=[]):
            return isolation.isolate(self.b,ISSUE,OP)

    def test_pause_only_enablement_with_durable_original_and_idempotent_receipt(self):
        receipt=self.apply();self.assertEqual(receipt['paused'],1);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(self.apply(),receipt)
        with self.b.db() as con:
            routes={r[0]:json.loads(r[1]) for r in con.execute('SELECT * FROM delivery_routes')}
            original=json.loads(con.execute('SELECT original FROM controller_route_isolations').fetchone()[0])
        self.assertEqual(routes[ISSUE],self.target);self.assertEqual(routes[OLD],{**self.old,'enabled':False})
        self.assertEqual(original[OLD],self.old)

    def test_unsealed_or_active_work_cannot_pause_any_route(self):
        with self.b.db() as con:con.execute("INSERT INTO leases VALUES('running')")
        with self.assertRaises(ValueError):self.apply()
        with self.b.db() as con:
            con.execute('DELETE FROM leases');con.execute("UPDATE controller_maintenance SET stage='released'")
        with self.assertRaises(ValueError):self.apply()

    def test_replay_cannot_hide_changed_contract_or_change_target(self):
        self.apply()
        with self.b.db() as con:con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
            (json.dumps({**self.old,'enabled':False,'contract':'drift'}),OLD))
        with self.assertRaisesRegex(ValueError,'drift'):self.apply()
