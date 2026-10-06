import json
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publication_access import recovery_evidence, container_command
from types import SimpleNamespace


class PublicationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.block=dict(payload=json.dumps(dict(reason='PermissionError [Errno 13] reading /opt/data/governance/execution.json')))
        self.proof=dict(passed=True,fingerprint='new',files=['/opt/data/governance/execution.json'])

    def test_actual_error_survives_cleared_task_failure(self):
        result=recovery_evidence(self.db,'t_test',None,self.block,self.proof)
        self.assertTrue(result['can_retry'])
        self.assertIn('PermissionError',result['last_error'])

    def test_failed_preflight_prevents_retry(self):
        self.proof['passed']=False
        self.assertFalse(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])

    def test_policy_requires_remote_evidence(self):
        self.block['payload']=json.dumps(dict(reason='HTTP 405 Merge commits are not allowed'))
        self.assertFalse(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])
        self.proof['remote_policy']={'passed':True}
        self.assertTrue(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])

    def test_same_policy_evidence_prevents_retry(self):
        self.db.execute('CREATE TABLE publication_failures(task,run,error,preflight_fingerprint)')
        self.db.execute('INSERT INTO publication_failures VALUES(?,?,?,?)',('t_test',64,'HTTP 405 Merge commits are not allowed','new'))
        self.proof['remote_policy']={'passed':True}
        self.assertFalse(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])

    def test_unknown_failure_never_retries_on_read_access_alone(self):
        self.block['payload']=json.dumps(dict(reason='GitHub rejected current CI'))
        self.assertFalse(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])

    def test_untested_path_prevents_retry(self):
        self.proof['files']=[]
        self.assertFalse(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])

    def test_same_preflight_after_failure_prevents_retry(self):
        self.db.execute('CREATE TABLE publication_failures(task,run,error,preflight_fingerprint)')
        self.db.execute('INSERT INTO publication_failures VALUES(?,?,?,?)',('t_test',58,'PermissionError /opt/data/governance/execution.json','new'))
        self.assertFalse(recovery_evidence(self.db,'t_test',None,self.block,self.proof)['can_retry'])

    def test_preflight_and_merge_share_minimum_read_capability(self):
        c=SimpleNamespace(image='local:test',volume='private')
        for preflight in (True,False):
            command=container_command(c,'t_test',preflight)
            self.assertIn('--cap-drop=ALL',command)
            self.assertIn('--cap-add=DAC_READ_SEARCH',command)
            self.assertIn('--read-only',command)
            self.assertFalse(any('docker.sock' in x for x in command))
            self.assertIn('--network=none' if preflight else '--network=bridge',command)
