import json
import sqlite3
import unittest
from broker import maintenance_job_clock as clock


class MaintenanceClockTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE controller_maintenance(stage TEXT,receipt TEXT)')

    def record(self,stage,start,end=None,namespace='owned'):
        self.con.execute('INSERT INTO controller_maintenance VALUES(?,?)',(stage,json.dumps(dict(
            namespace=namespace,sealed_at=start,released_at=end))))

    def test_only_proved_sealed_downtime_extends_original_deadline(self):
        self.record('released',100,1100)
        self.assertEqual(clock.deadline(self.con,'owned',600,1200),1600)
        self.assertEqual(clock.deadline(self.con,'owned',600,1300),1600)
        self.assertEqual(clock.deadline(self.con,'other',600,1200),600)

    def test_active_seal_forbids_jobs_and_draining_does_not_extend_budget(self):
        self.record('draining',100)
        self.assertEqual(clock.deadline(self.con,'owned',600,700),600)
        self.record('sealed',100)
        with self.assertRaises(TimeoutError):clock.deadline(self.con,'owned',600,700)

    def test_intervals_before_job_and_overlapping_records_cannot_grant_extra_time(self):
        self.record('released',-100,50);self.record('released',0,100);self.record('released',50,150)
        self.assertEqual(clock.deadline(self.con,'owned',600,700),750)

    def test_invalid_interval_fails_closed(self):
        self.record('released',100,10)
        with self.assertRaises(ValueError):clock.deadline(self.con,'owned',600,700)
