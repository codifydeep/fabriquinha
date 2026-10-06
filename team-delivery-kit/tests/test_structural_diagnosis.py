"""Offline structural evidence fixtures; never autonomous delivery evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sqlite3
import contextlib
from types import SimpleNamespace
from test_portable_contract import contract
from broker import structural_diagnosis as diagnosis


class StructuralEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/'base';self.candidate=Path(self.tmp.name)/'candidate';self.previous=Path(self.tmp.name)/'previous'
        for root in (self.base,self.candidate,self.previous):root.mkdir()
        files={'AGENTS.md':b'rules','app.py':b'pass\n','tests/test_old.py':b'old\n'}
        spec=json.dumps(contract()).encode();files['contract.json']=spec
        base={}
        for name,content in files.items():
            path=self.base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            base[name]=hashlib.sha256(content).hexdigest()
        (self.base/'manifest.json').write_text(json.dumps({'base_sha':'a'*40,'files':base}))
        for root in (self.candidate,self.previous):
            manifest={}
            for name,content in {**{k:v for k,v in files.items() if k!='contract.json'},'tests/test_new.py':b'new\n'}.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
                manifest[name]={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}
            (root/'manifest.json').write_text(json.dumps({'files':manifest}))

    def report(self):return diagnosis.inspect(str(self.base),str(self.candidate),str(self.previous))

    def test_exact_red_and_zero_product_delta_is_not_green(self):
        r=self.report()
        self.assertEqual(r['category'],'missing_product_delta')
        self.assertEqual(r['changed_product_files'],[])
        self.assertEqual(r['new_test_files'],['tests/test_new.py'])
        self.assertEqual(r['product_read_files'],['app.py'])
        self.assertFalse(r['suite_executed']);self.assertFalse(r['delivery_approval'])

    def test_changed_or_unhashed_previous_and_invalid_candidate_rejected(self):
        (self.previous/'app.py').write_text('changed')
        with self.assertRaises(ValueError):self.report()
        (self.previous/'app.py').write_bytes(b'pass\n')
        (self.candidate/'tests/test_new.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.report()

    def test_product_change_cannot_be_relabelled_missing_delta(self):
        p=self.candidate/'app.py';p.write_bytes(b'changed\n')
        m=json.loads((self.candidate/'manifest.json').read_text());m['files']['app.py']={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':len(p.read_bytes())}
        (self.candidate/'manifest.json').write_text(json.dumps(m))
        with self.assertRaises(ValueError):self.report()


class StructuralRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE leases(status TEXT)')
        @contextlib.contextmanager
        def db():
            with self.con:yield self.con
        self.b=SimpleNamespace(db=db)
        self.data=dict(source_task='author',failure_category='missing_delivery_artifacts',target='cto',decision=dict(action='escalate_cto'))
        self.row=dict(source_task='author',stage='technical_decision_required',data=json.dumps(self.data))

    def test_eligible_experiment_runs_once_and_records_success(self):
        with patch.object(diagnosis,'register',return_value=dict(candidate_manifest_sha256='a'*64)) as run:
            self.assertTrue(diagnosis.reconcile(self.b,self.row));self.assertTrue(diagnosis.reconcile(self.b,self.row))
            run.assert_called_once_with(self.b,'author')
        saved=json.loads(self.con.execute('SELECT state FROM structural_diagnostic_attempts').fetchone()[0])
        self.assertEqual(saved['stage'],'complete');self.assertFalse(saved['delivery_approval'])

    def test_failure_remains_visible_without_identical_retry_and_active_worker_defers(self):
        self.con.execute("INSERT INTO leases VALUES('running')")
        with patch.object(diagnosis,'register',side_effect=ValueError('fixed experiment failed')) as run:
            self.assertTrue(diagnosis.reconcile(self.b,self.row));run.assert_not_called()
            self.con.execute('DELETE FROM leases')
            self.assertTrue(diagnosis.reconcile(self.b,self.row));self.assertTrue(diagnosis.reconcile(self.b,self.row))
            run.assert_called_once()
        saved=json.loads(self.con.execute('SELECT state FROM structural_diagnostic_attempts').fetchone()[0])
        self.assertEqual(saved['stage'],'blocked');self.assertEqual(saved['failure_category'],'ValueError')

    def test_unrelated_handoff_or_prior_experiment_is_not_replayed(self):
        with patch.object(diagnosis,'register') as run:
            for changes in (dict(stage='accepted'),dict(data=json.dumps({**self.data,'structural_diagnosis':{}})),dict(data='{}')):
                self.assertFalse(diagnosis.reconcile(self.b,{**self.row,**changes}))
            run.assert_not_called()

    def test_restart_intent_has_at_most_one_resume(self):
        diagnosis.initialize(self.con)
        self.con.execute('INSERT INTO structural_diagnostic_attempts VALUES(?,?)',('author',json.dumps(dict(stage='intent',starts=1,delivery_approval=False))))
        with patch.object(diagnosis,'register',return_value=dict(candidate_manifest_sha256='a'*64)) as run:
            self.assertTrue(diagnosis.reconcile(self.b,self.row));run.assert_called_once()
        self.con.execute('UPDATE structural_diagnostic_attempts SET state=?',(json.dumps(dict(stage='intent',starts=2,delivery_approval=False)),))
        with patch.object(diagnosis,'register') as run:
            self.assertTrue(diagnosis.reconcile(self.b,self.row));run.assert_not_called()
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM structural_diagnostic_attempts').fetchone()[0])['stage'],'blocked')
