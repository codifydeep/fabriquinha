"""Quiescent pin changes preserve history; these are not delivery evidence."""
import json
from pathlib import Path
import plistlib
import sqlite3
import unittest
import uuid
from unittest.mock import patch
import migrate_quality_candidate_pin as migration
import quality_candidate_dispatch as dispatch
import quality_candidate_service as service
import test_quality_candidate_service as fixtures


class Effects:
    def __init__(self, root):
        self.root=root;self.running=False;self.fail_registration=False
    def about(self,*args):
        return dict(maintenance=True,v2_enabled=False,implementation_enabled=False,queue_supported=True)
    def idle(self,*args):pass
    def stopped(self,*args):
        if self.running:raise ValueError('service running')
    def helpers(self,*args):pass
    def login(self,*args):return self.root/'login.plist'
    def register(self,path,pin):
        if self.fail_registration:raise RuntimeError('interrupted after journal migration')
        with patch('quality_delivery_candidate.repository'):
            return service.register(path,pin)


class PinMigrationTests(unittest.TestCase):
    # Reuse private configuration setup, not the service test cases themselves.
    def setUp(self):
        fixtures.CandidateServiceTests.setUp(self)
        self.fx=Effects(self.root);self.operation=str(uuid.uuid4())
        self.image='sha256:'+'b'*64
        with patch.object(dispatch,'advance_remote',side_effect=dispatch.Pending):
            dispatch.tick(self.authority,self.value['repositories'],self.root)
        self.authority.paused=True;service.run_once(self.path,self.pin)
        self.database=next((self.root/'quality-candidate-dispatch').glob('*.sqlite'))
        with sqlite3.connect(self.database) as con:self.before=migration.queue(con)[1:]
        with patch('quality_delivery_candidate.repository'):
            registered=service.register(self.path,self.pin)
        service.write_once(self.fx.login(),Path(registered['plist']).read_bytes())
        self.child=self.root/'quality-git-candidates';self.child.mkdir(mode=0o700)
        service.write_once(self.child/'preserved.json',b'{"evidence":"unchanged"}')

    def migrate(self):
        return migration.migrate(self.path,self.pin,self.image,self.operation,effects=self.fx)

    def test_migration_preserves_tasks_deadlines_tickets_and_child_journals(self):
        before=migration.children(self.root)
        result=self.migrate()
        self.assertEqual(result['stage'],'pins_migrated_service_stopped')
        with sqlite3.connect(self.database) as con:
            row,history,count=migration.queue(con)
        self.assertEqual((history,count),self.before)
        self.assertEqual(json.loads(row[0])['image'],self.image)
        self.assertEqual(migration.children(self.root),before)
        with patch.object(self.authority,'image',self.image):
            status=service.status(result['new_config'],result['new_pin'])
        self.assertEqual(status['service']['result']['stage'],'maintenance')
        login=plistlib.loads(self.fx.login().read_bytes())
        self.assertIn(result['new_pin'],login['ProgramArguments'])
        self.assertEqual(self.migrate(),result)

    def test_crash_latch_is_not_cleared_by_new_pin(self):
        with patch.object(dispatch,'tick',side_effect=RuntimeError):
            service.run_once(self.path,self.pin);before=service.run_once(self.path,self.pin)
        self.assertEqual(before['stage'],'crash_escalation')
        result=self.migrate()
        with patch.object(self.authority,'image',self.image):
            self.assertEqual(service.status(result['new_config'],result['new_pin'])['service'],before)

    def test_interruption_after_queue_and_service_change_resumes_without_reset(self):
        self.fx.fail_registration=True
        with self.assertRaises(RuntimeError):self.migrate()
        self.fx.fail_registration=False
        result=self.migrate()
        self.assertEqual(result['task_count'],self.before[1])
        self.assertEqual(result['history_sha256'],self.before[0])

    def test_loaded_service_blocks_before_queue_change(self):
        self.fx.running=True
        with self.assertRaises(ValueError):self.migrate()
        with sqlite3.connect(self.database) as con:
            self.assertEqual(json.loads(migration.queue(con)[0][0])['image'],self.value['image'])

    def test_login_drift_is_not_overwritten(self):
        self.fx.fail_registration=True
        with self.assertRaises(RuntimeError):self.migrate()
        self.fx.login().write_bytes(b'changed by another operator')
        self.fx.fail_registration=False
        with self.assertRaises(ValueError):self.migrate()
        self.assertEqual(self.fx.login().read_bytes(),b'changed by another operator')

    def test_pending_tick_intent_cannot_be_reclassified_by_migration(self):
        with patch.object(dispatch,'tick',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):service.run_once(self.path,self.pin)
        with self.assertRaises(ValueError):self.migrate()

    def test_changed_child_evidence_blocks_resume(self):
        self.fx.fail_registration=True
        with self.assertRaises(RuntimeError):self.migrate()
        (self.child/'preserved.json').write_bytes(b'changed evidence')
        self.fx.fail_registration=False
        with self.assertRaises(ValueError):self.migrate()

    def test_backup_history_corruption_blocks_resume(self):
        self.fx.fail_registration=True
        with self.assertRaises(RuntimeError):self.migrate()
        backup=self.root/'backups'/('candidate-pin-migration-'+self.operation)/'queue.sqlite'
        with sqlite3.connect(backup) as con:con.execute('UPDATE meta SET ticket=ticket+1')
        self.fx.fail_registration=False
        with self.assertRaises(ValueError):self.migrate()


if __name__=='__main__':unittest.main()
