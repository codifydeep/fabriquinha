import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from broker import stopped_cycle_recovery as recovery


class StoppedCycleRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.path=Path(directory.name)/'leases.sqlite'
        self.op='11111111-1111-4111-8111-111111111111'
        self.identity=dict(operation_id=self.op,namespace='delivery-kit-test',container_id='a'*64,
            state=dict(Running=False,Pid=0,Status='exited',StartedAt='2026-10-18T00:00:00Z',FinishedAt='2026-10-20T00:00:00Z'))
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executescript('CREATE TABLE controller_maintenance(operation_id PRIMARY KEY,stage,receipt);'
                'CREATE TABLE leases(request_id,status);CREATE TABLE grants(request_id,used,deadline);'
                'CREATE TABLE controller_maintenance_cycles(cycle_id PRIMARY KEY,namespace,stage);'
                'CREATE TABLE workflows(id PRIMARY KEY,state);')
            c.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(self.op,'draining',json.dumps(dict(namespace='delivery-kit-test'))))
            c.execute("INSERT INTO controller_maintenance_cycles VALUES('legacy','delivery-kit-test','active')")
            c.execute("INSERT INTO workflows VALUES('product','blocked-not-approved')")

    def test_recovery_preserves_backup_restore_and_product_state_without_faking_cycle_completion(self):
        proof=recovery.recover(self.path,self.identity)
        self.assertEqual(proof['interrupted_cycles'],['legacy']);self.assertFalse(proof['cycle_completed'])
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['source_reset'])
        self.assertEqual(recovery.recover(self.path,self.identity),proof)
        with closing(sqlite3.connect(self.path)) as c,c:
            self.assertEqual(c.execute('SELECT state FROM workflows').fetchone()[0],'blocked-not-approved')
            self.assertEqual(c.execute('SELECT stage FROM controller_maintenance_cycles').fetchone()[0],'interrupted')
            self.assertEqual(c.execute('SELECT stage FROM controller_maintenance').fetchone()[0],'draining')
        with closing(sqlite3.connect(proof['backup'])) as c,c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('SELECT stage FROM controller_maintenance_cycles').fetchone()[0],'active')

    def test_live_process_active_lease_or_wrong_operation_never_repairs_cycle(self):
        for state in ({**self.identity['state'],'Running':True},{**self.identity['state'],'Pid':1}):
            with self.assertRaises(ValueError):recovery.recover(self.path,{**self.identity,'state':state})
        with closing(sqlite3.connect(self.path)) as c,c:c.execute("INSERT INTO leases VALUES('worker','running')")
        with self.assertRaises(ValueError):recovery.recover(self.path,self.identity)
        self.assertEqual(list(self.path.parent.glob('legacy-cycle-backup-*')),[])

    def test_unknown_backup_effect_is_preserved_not_overwritten_or_assumed_complete(self):
        existing=self.path.parent/('legacy-cycle-backup-'+self.op+'.sqlite');existing.write_bytes(b'unknown')
        with self.assertRaises(ValueError):recovery.recover(self.path,self.identity)
        self.assertEqual(existing.read_bytes(),b'unknown')
        with closing(sqlite3.connect(self.path)) as c,c:self.assertEqual(c.execute('SELECT stage FROM controller_maintenance_cycles').fetchone()[0],'active')
