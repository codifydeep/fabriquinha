import json
import sqlite3
import tempfile
from pathlib import Path
from contextlib import contextmanager
import unittest
from broker import transport_qualification as q


class TransportQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.STATE=Path(self.temp.name);self.IMAGE='sha256:'+'a'*64
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.executescript('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,data TEXT);'
            'CREATE TABLE test_first_red(issue_id TEXT);CREATE TABLE leases(status TEXT);'
            'CREATE TABLE unchanged_seed_diagnoses(source_task TEXT,state TEXT);')
        self.diag=dict(kind='unchanged_seed_read_only_failure',issue_id='issue',task_id='source',manifest_sha256='b'*64,
            proxy_failure_cause_proven=False,write_executed=False,tests_executed=False,red_verified=False,delivery_approval=False)
        self.data=dict(error='test_first_cto_requires_replanning',decision=dict(action='escalate_cto'),
            unchanged_seed_diagnosis_replay={'previous_cto_task':'prior-cto'},diagnostic=self.diag)
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?)',('source','issue','test_first_blocked',json.dumps(self.data)))
        self.con.execute('INSERT INTO unchanged_seed_diagnoses VALUES(?,?)',('source',json.dumps(dict(stage='passed',receipt=self.diag))))
        self.config=dict(native_probe='11111111-1111-4111-8111-111111111111',
            acp_probe='22222222-2222-4222-8222-222222222222',worker_image=self.IMAGE,writer_sha256='c'*64)
        self.native=dict(schema='native-patch-probe-v1',status='passed',execution_id=self.config['native_probe'],
            worker_image=self.IMAGE,model_calls=0,delivery_approval=False,product_retry=False,
            inspection=dict(uid=10000,writer_sha256='c'*64,baseline_unchanged=True,credentials_absent=True,
                invalid_patch_rejected=True,fixed_syntax_error=True,rejected_patch_preserved_bytes=True,
                valid_patch_success=True,exact_quotes_preserved=True))
        self.acp=dict(self.native,schema='fixed-acp-patch-probe-v1',execution_id=self.config['acp_probe'],
            model_authorship=False,actual_patch_calls=2,actual_read_calls=2,paired_patch_results=1,
            syntax_rejected_patch_calls=1,tool_protocol_valid=True,inspection=dict(self.native['inspection'],requests=5))
        self.write(self.STATE/'transport-qualification.json',self.config)
        folder=self.STATE/'synthetic-probe-evidence';folder.mkdir(mode=0o700)
        for value in (self.native,self.acp):self.write(folder/(value['execution_id']+'.json'),dict(result=value))

    def write(self,path,value):
        path.write_text(json.dumps(value));path.chmod(0o600)

    @contextmanager
    def db(self):
        with self.con:yield self.con

    def test_passed_controls_bind_snapshot_and_never_grant_authority(self):
        receipt=q.capture(self,'issue','source');self.assertIsNotNone(receipt)
        self.assertEqual(q.capture(self,'issue','source'),receipt)
        for flag in ('historical_cause_proven','model_authorship','author_retry_authorized','delivery_approval'):
            self.assertIs(receipt[flag],False)
        self.assertEqual(receipt['manifest_sha256'],self.diag['manifest_sha256'])
        data=dict(self.data,transport_qualification_replay=dict(certificate=receipt))
        self.assertTrue(q.qualified(self.con,'issue','source',data,self.IMAGE))
        self.assertFalse(q.qualified(self.con,'issue','source',data,'sha256:'+'d'*64))
        self.assertFalse(q.qualified(self.con,'other','source',data,self.IMAGE))
        data['diagnostic']=dict(self.diag,manifest_sha256='e'*64)
        self.assertFalse(q.qualified(self.con,'issue','source',data,self.IMAGE))

    def test_red_active_lease_and_consumed_replay_do_not_rearm(self):
        self.con.execute('INSERT INTO test_first_red VALUES(?)',('issue',));self.assertIsNone(q.capture(self,'issue','source'))
        self.con.execute('DELETE FROM test_first_red');self.con.execute('INSERT INTO leases VALUES(?)',('running',))
        self.assertIsNone(q.capture(self,'issue','source'));self.con.execute('DELETE FROM leases')
        self.data['transport_qualification_replay']={'certificate':{}}
        self.con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(self.data),))
        self.assertIsNone(q.capture(self,'issue','source'))

    def test_failed_or_inconsistent_probe_is_not_evidence(self):
        for value,key,bad in ((self.native,'status','failed'),(self.acp,'actual_patch_calls',3),
                             (self.acp,'model_authorship',True),(self.native,'model_calls',1)):
            old=value[key];value[key]=bad
            with self.assertRaises(ValueError):q.validate_probes(self.native,self.acp,self.IMAGE,'c'*64)
            value[key]=old
        self.acp['inspection']['writer_sha256']='f'*64
        with self.assertRaises(ValueError):q.validate_probes(self.native,self.acp,self.IMAGE,'c'*64)

    def test_private_configuration_and_probe_bindings_are_enforced(self):
        path=self.STATE/'transport-qualification.json';path.chmod(0o644)
        with self.assertRaises(ValueError):q.capture(self,'issue','source')
        self.write(path,dict(self.config,worker_image='sha256:'+'d'*64))
        with self.assertRaises(ValueError):q.capture(self,'issue','source')
        self.write(path,self.config)
        archive=self.STATE/'synthetic-probe-evidence'/(self.config['native_probe']+'.json')
        self.write(archive,dict(result=dict(self.native,execution_id=self.config['acp_probe'])))
        with self.assertRaises(ValueError):q.capture(self,'issue','source')

    def test_changed_snapshot_or_qualification_identity_is_rejected(self):
        q.capture(self,'issue','source')
        self.config['writer_sha256']='d'*64
        self.native['inspection']['writer_sha256']='d'*64;self.acp['inspection']['writer_sha256']='d'*64
        self.write(self.STATE/'transport-qualification.json',self.config)
        for value in (self.native,self.acp):self.write(self.STATE/'synthetic-probe-evidence'/(value['execution_id']+'.json'),dict(result=value))
        with self.assertRaisesRegex(ValueError,'identity drift'):q.capture(self,'issue','source')
