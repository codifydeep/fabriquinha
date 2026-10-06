import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from delivery_gate import verify_report_evidence
from delivery_receipts import EvidenceStore


class ReportEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=EvidenceStore(self.tmp.name,'r2')
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,payload TEXT)')
        self.release=dict(attempt='r2',branch='release/v0.1')
        self.report=dict(commit='a'*40)
        self.files={}
        for kind,owner,reviewer,names in [
            ('qa','quality_security','techlead',['unit','integration','e2e','regression','security']),
            ('deployment','devops','quality_security',['compose','health','rollback'])]:
            self.db.execute('INSERT INTO task_events(task_id,kind,payload) VALUES(?,?,?)',
                (kind,'review_requested',json.dumps(dict(implementer=owner,reviewer=reviewer))))
            checks=[]
            for name in names:
                filename=kind+'/'+name+'.log'
                output=(name+' passed\n').encode()
                self.files[filename]=output
                checks.append(dict(name=name,command='fixture '+name,exit_code=0,
                    output_file=filename,output_sha256=hashlib.sha256(output).hexdigest()))
            filename=kind+'/report.json'
            raw=json.dumps(dict(attempt='r2',commit='a'*40,checks=checks)).encode()
            self.files[filename]=raw
            self.report[kind]=dict(card=kind,evidence=filename,evidence_sha256=hashlib.sha256(raw).hexdigest())

    def verify(self):
        with patch('delivery_gate.read_git_evidence',side_effect=lambda repo,branch,path:self.files[path]):
            return verify_report_evidence(self.db,'.',self.release,self.report,self.store)

    def test_all_reports_and_logs_survive_source_removal(self):
        artifacts=self.verify()
        digest=self.store.save(dict(kind='homologation',artifacts=artifacts))
        self.files.clear()
        self.assertEqual(len(self.store.load(digest)['artifacts']),10)

    def test_missing_reviewer_rejected(self):
        self.db.execute("UPDATE task_events SET payload=? WHERE task_id='qa'",
            (json.dumps(dict(implementer='quality_security')),))
        with self.assertRaisesRegex(ValueError,'authorship'):
            self.verify()

    def test_tampered_command_output_rejected(self):
        self.files['qa/unit.log']=b'failed'
        with self.assertRaisesRegex(ValueError,'checksum'):
            self.verify()

    def test_other_attempt_rejected_even_with_matching_hash(self):
        path=self.report['qa']['evidence']
        data=json.loads(self.files[path])
        data['attempt']='old'
        self.files[path]=json.dumps(data).encode()
        self.report['qa']['evidence_sha256']=hashlib.sha256(self.files[path]).hexdigest()
        with self.assertRaisesRegex(ValueError,'another attempt'):
            self.verify()
