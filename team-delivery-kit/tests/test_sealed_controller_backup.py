import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

source=Path(__file__).resolve().parents[1]/'scripts'/'backup_sealed_controller.py'
spec=importlib.util.spec_from_file_location('sealed_backup_script',source)
script=importlib.util.module_from_spec(spec);spec.loader.exec_module(script)


class SealedBackupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.operation='2e2aeb1d-f33a-44b0-ba39-9a5b6cd9d2eb'
        self.state=dict(operation_id=self.operation,stage='sealed')
        self.con.executescript('CREATE TABLE controller_maintenance(operation_id TEXT,receipt TEXT);'
            'CREATE TABLE leases(status TEXT);CREATE TABLE protected(value TEXT);INSERT INTO protected VALUES("preserve");')
        self.con.execute('INSERT INTO controller_maintenance VALUES(?,?)',(self.operation,json.dumps(self.state)))
        self.con.commit()
        @contextlib.contextmanager
        def db():yield self.con
        self.b=SimpleNamespace(STATE=self.root,LOCK=threading.RLock(),db=db)
        self.active=[]
        self.m=SimpleNamespace(current=lambda con:self.state,native_active=lambda b:self.active)

    def execute(self):
        output=io.StringIO()
        with patch.dict('sys.modules',{'broker':self.b,'controller_maintenance':self.m}),\
                patch('sys.argv',['backup',self.operation]),contextlib.redirect_stdout(output):
            try:exec(compile(script.PROGRAM,'sealed-backup','exec'),{})
            except SystemExit as outcome:self.assertEqual(outcome.code,0)
        return json.loads(output.getvalue())

    def test_backup_restores_exact_rows_privately_and_never_replays(self):
        receipt=self.execute();path=Path(receipt['path']);before=path.read_bytes()
        self.assertEqual(receipt['restore_integrity'],'ok')
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        restored=sqlite3.connect(path);self.addCleanup(restored.close)
        self.assertEqual(restored.execute('SELECT value FROM protected').fetchone(),('preserve',))
        self.assertIs(receipt['delivery_approval'],False)
        identity=(path.stat().st_ino,path.stat().st_mtime_ns);files=set(self.root.iterdir())
        self.con.execute('UPDATE protected SET value="changed after backup"');self.con.commit()
        self.assertEqual(self.execute(),receipt)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual((path.stat().st_ino,path.stat().st_mtime_ns),identity)
        self.assertEqual(set(self.root.iterdir()),files)
        ack=self.root/('sealed-backup-'+self.operation+'.receipt.json')
        self.assertEqual(ack.stat().st_mode&0o777,0o600)

    def test_existing_backup_without_receipt_is_observed_never_recreated_or_approved(self):
        path=self.root/('sealed-backup-'+self.operation+'.sqlite');path.write_bytes(b'unknown acknowledgment')
        receipt=self.execute();self.assertEqual(receipt['stage'],'observe_existing_backup')
        self.assertFalse(receipt['backup_repeated']);self.assertFalse(receipt['delivery_approval'])
        self.assertNotIn('backup_integrity',receipt)
        self.assertEqual(path.read_bytes(),b'unknown acknowledgment');self.assertEqual(set(self.root.iterdir()),{path})

    def test_changed_backup_or_false_success_receipt_is_rejected(self):
        receipt=self.execute();path=Path(receipt['path']);before=path.read_bytes()
        path.write_bytes(before+b'corrupt')
        with self.assertRaises(ValueError):self.execute()
        path.write_bytes(before)
        ack=self.root/('sealed-backup-'+self.operation+'.receipt.json')
        for changed in (dict(delivery_approval=True),dict(active_leases=1),dict(operation_id='foreign')):
            ack.write_text(json.dumps({**receipt,**changed}))
            with self.assertRaises(ValueError):self.execute()

    def test_unsealed_wrong_operation_or_active_work_creates_no_backup(self):
        for mutate in (lambda:self.state.update(stage='draining'),
                lambda:self.state.update(operation_id='foreign'),lambda:self.active.append('task')):
            old=dict(self.state);mutate()
            with self.assertRaises(ValueError):self.execute()
            self.assertEqual(list(self.root.iterdir()),[])
            self.state=old;self.active=[]
        self.con.execute('INSERT INTO leases VALUES("closing")');self.con.commit()
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(list(self.root.iterdir()),[])
