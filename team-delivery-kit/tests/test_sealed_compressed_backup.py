from contextlib import closing, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('sealed_backup_wrapper',Path(__file__).resolve().parents[1]/'scripts'/'backup_sealed_controller.py')
wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)


class SealedCompressedTests(unittest.TestCase):
    def setup_state(self,root,con,stage='sealed',active=0):
        state=dict(operation_id='test-operation',stage=stage)
        con.execute('CREATE TABLE controller_maintenance(operation_id,receipt)')
        con.execute('INSERT INTO controller_maintenance VALUES(?,?)',('test-operation',json.dumps(state)))
        con.execute('CREATE TABLE leases(status)');con.commit()
        return SimpleNamespace(STATE=root,LOCK=threading.Lock(),db=lambda:con),SimpleNamespace(current=lambda c:state,native_active=lambda b:active)

    def run_program(self,b,m,free=10**12,backup_id=None):
        output=io.StringIO()
        argv=['backup','test-operation',str(free)]+([backup_id] if backup_id else [])
        with patch.dict(sys.modules,{'broker':b,'controller_maintenance':m}),patch.object(sys,'argv',argv),redirect_stdout(output):
            exec(compile(wrapper.compressed_program(),'<trusted-backup>','exec'),{})
        return json.loads(output.getvalue())

    def test_durable_receipt_observed_without_recreating_backup(self):
        with tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as con:
            root=Path(d);b,m=self.setup_state(root,con)
            first=self.run_program(b,m)
            archive=Path(first['path']);before=archive.stat().st_mtime_ns
            second=self.run_program(b,m,free=0)
            self.assertEqual(first,second);self.assertEqual(before,archive.stat().st_mtime_ns)
            self.assertFalse(first['delivery_approval']);self.assertFalse(list(root.glob('*proof*')))

    def test_uncertain_scratch_is_observed_never_repeated(self):
        with tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as con:
            root=Path(d);b,m=self.setup_state(root,con)
            scratch=root/'sealed-compressed-proof-test-operation.sqlite';scratch.write_bytes(b'unknown')
            result=self.run_program(b,m)
            self.assertEqual(result['stage'],'observe_existing_backup');self.assertEqual(scratch.read_bytes(),b'unknown')
            self.assertEqual(len(list(root.iterdir())),1)

    def test_unsealed_active_or_low_space_rejected_before_any_file(self):
        for stage,active,free in [('draining',0,10**12),('sealed',1,10**12),('sealed',0,0)]:
            with self.subTest(stage=stage,active=active,free=free),tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as con:
                root=Path(d);b,m=self.setup_state(root,con,stage,active)
                with self.assertRaises(ValueError):self.run_program(b,m,free)
                self.assertFalse(list(root.iterdir()))

    def test_cached_archive_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as con:
            root=Path(d);b,m=self.setup_state(root,con)
            first=self.run_program(b,m);Path(first['path']).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):self.run_program(b,m)

    def test_fresh_backup_does_not_require_releasing_or_overwriting_the_old_seal(self):
        with tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as con:
            root=Path(d);b,m=self.setup_state(root,con)
            first=self.run_program(b,m);original=Path(first['path']).read_bytes()
            con.execute('CREATE TABLE progress(value)');con.execute('INSERT INTO progress VALUES(1)');con.commit()
            key='c0000000-0000-4000-8000-000000000001'
            second=self.run_program(b,m,backup_id=key)
            self.assertEqual(first['operation_id'],second['operation_id']);self.assertEqual(second['backup_id'],key)
            self.assertNotEqual(first['sha256'],second['sha256']);self.assertEqual(Path(first['path']).read_bytes(),original)
            self.assertEqual(self.run_program(b,m,backup_id=key),second)
            self.assertEqual(m.current(con)['stage'],'sealed')
