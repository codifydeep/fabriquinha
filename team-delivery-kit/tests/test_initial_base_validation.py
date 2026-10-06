import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from test_portable_contract import contract
from broker.initial_base_inspect import inspect
from broker import initial_base_validation as validation


class InitialInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.spec=contract();files={}
        for name in ('AGENTS.md','app.py','tests/test_old.py'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'original\n')
            files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        raw=json.dumps(self.spec).encode();(self.root/'contract.json').write_bytes(raw)
        files['contract.json']=hashlib.sha256(raw).hexdigest()
        raw=json.dumps(dict(base_sha='a'*40,files=files)).encode()
        (self.root/'manifest.json').write_bytes(raw);self.sha=hashlib.sha256(raw).hexdigest()

    def test_inspection_binds_every_file_and_excludes_not_yet_written_new_test(self):
        proof=inspect(self.root,self.sha)
        self.assertEqual(list(proof['baseline_test_sha256']),['tests/test_old.py'])
        self.assertEqual(proof['test_command'],self.spec['test_command'])
        self.assertEqual(proof['manifest_sha256'],self.sha)

    def test_changed_file_manifest_or_undeclared_entry_cannot_qualify(self):
        with self.assertRaises(ValueError):inspect(self.root,'0'*64)
        (self.root/'extra').write_bytes(b'no')
        with self.assertRaises(ValueError):inspect(self.root,self.sha)
        (self.root/'extra').unlink();(self.root/'app.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):inspect(self.root,self.sha)


class InitialCaptureTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.executescript('CREATE TABLE test_decompositions(source_task,config,state);CREATE TABLE leases(status);')
        self.con.execute('INSERT INTO test_decompositions VALUES(?,?,?)',
            ('source',json.dumps(dict(issue_id='issue',cto='cto')),json.dumps(dict(stage='proposal_ready'))))
        class Connection:
            def __enter__(_):return self.con
            def __exit__(_,kind,value,tb):self.con.commit() if kind is None else self.con.rollback()
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=lambda:Connection(),PREFIX='delivery-kit-port2',OWNER='owner',IMAGE='sha256:'+'1'*64,
            issue_base=Mock(return_value=dict(base_sha='a'*40,manifest_sha256='b'*64,volume='base')),
            run_portable_suite=Mock(return_value=dict(tests=243,test_image='python@sha256:'+'2'*64,
                test_command=['python3','-m','unittest'],output_sha256='c'*64)))
        self.spec=dict(base_sha='a'*40,manifest_sha256='b'*64,baseline_test_sha256={'tests/old.py':'d'*64},
                       contract_sha256='e'*64)
        self.b.docker_stdout=Mock(return_value=json.dumps(self.spec))
        self.created=False
        def docker(method,path,payload=None):
            if path.startswith('/containers/create'):
                self.created=True;self.payload=payload;return {'Id':'job'}
            if path.endswith('/json'):
                return dict(Id='job',State=dict(Running=False,ExitCode=0),Config=dict(Labels=self.payload['Labels'])) if self.created else None
            return {}
        self.b.docker=Mock(side_effect=docker)

    def test_capture_is_durable_readonly_and_idempotent(self):
        proof=validation.capture(self.b,'source')
        self.assertEqual(proof['tests'],243)
        self.assertEqual(proof['executed_by'],'controller_original_base_suite')
        self.assertEqual(validation.capture(self.b,'source'),proof)
        self.b.run_portable_suite.assert_called_once()
        self.assertTrue(self.payload['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(self.payload['HostConfig']['NetworkMode'],'none')
        self.assertTrue(all(m['ReadOnly'] for m in self.payload['HostConfig']['Mounts']))

    def test_failed_execution_stays_visible_without_automatic_retry(self):
        self.b.run_portable_suite.side_effect=ValueError('fixture failure')
        with self.assertRaises(ValueError):validation.capture(self.b,'source')
        with self.assertRaises(ValueError):validation.capture(self.b,'source')
        self.b.run_portable_suite.assert_called_once()
        row=self.con.execute('SELECT status,receipt FROM initial_base_validations').fetchone()
        self.assertEqual(row[0],'failed');self.assertEqual(json.loads(row[1])['owner'],'cto')
