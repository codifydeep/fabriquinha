"""Synthetic controller DB fixtures; never product delivery evidence."""
import copy
import json
import sqlite3
import unittest
from broker import incremental_evidence as adapter
from broker.incremental_checkpoints import digest


class IncrementalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.executescript('''
        CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id);
        CREATE TABLE grants(request_id,task_id,attempt,mode,used);
        CREATE TABLE leases(request_id,status);
        CREATE TABLE test_first_red(issue_id,task_id,receipt);
        CREATE TABLE review_suite_rpc(request_id,source_task,status,receipt,volume);
        CREATE TABLE review_bindings(request_id,source_task_id);
        CREATE TABLE test_revision_trials(issue_id,state);
        CREATE TABLE snapshots(task_id,volume,status);
        CREATE TABLE reviews(review_task_id,source_task_id,reviewer_agent_id,manifest_sha256,status);
        ''')
        self.suite=digest({'test_image':'image@sha256:'+'9'*64,'test_command':['python3','-m','unittest']})
        self.config=dict(source_task='source',proposal_sha256='a'*64,units=[dict(id='U1')],
            policy=dict(author='author',test_reviewer='lead',delivery_reviewer='cto',suite_sha256=self.suite))
        self.unit=dict(id='U1',base_manifest_sha256='b'*64,baseline_test_sha256={'tests/old.py':'c'*64},
                       prior_test_count=1,red_manifest_sha256='d'*64,red='e'*64,
                       new_test_sha256={'tests/new.py':'f'*64})
        self.bind('red','author','implementation')
        self.bind('review','lead','planning')
        self.proof=dict(evidence_version=2,exit_code=1,base_manifest_sha256='b'*64,
            manifest_sha256='d'*64,baseline_test_sha256={'tests/old.py':'c'*64},
            test_sha256={'tests/new.py':'f'*64},test_image='image@sha256:'+'9'*64,
            command=['python3','-m','unittest'],output_sha256='0'*64,test_count=2)
        self.saved=dict(issue_id='child',task_id='red',red=self.proof)
        self.con.execute('INSERT INTO test_first_red VALUES(?,?,?)',('child','red',json.dumps(self.saved)))
        self.prior=dict(executed_by='controller_offline_review_suite',exit_code=0,network='none',
            snapshot_mount='readonly',manifest_sha256='b'*64,source_task='prior',tests=1,
            test_image=self.proof['test_image'],test_command=self.proof['command'],output_sha256='1'*64)
        self.con.execute('INSERT INTO review_suite_rpc(request_id,source_task,status,receipt) VALUES(?,?,?,?)',('prior-run','prior','passed',json.dumps(self.prior)))
        self.con.execute('INSERT INTO review_bindings VALUES(?,?)',('prior-run','prior'))
        self.review=dict(status='approved',review_task='review',manifest_sha256='d'*64,
            read_contract='complete-lines-v2',decision=dict(action='approve_test_revision',
            manifest_sha256='d'*64,optional_files=[]),
            read_evidence={'/evidence/candidate/tests/new.py':dict(lines=10,total_lines=10)})
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('child',json.dumps(self.review)))

    def bind(self,task,agent,mode):
        self.con.execute('INSERT INTO native_bindings VALUES(?,?,?,?)',(task+'-req',task,agent,'child'))
        self.con.execute('INSERT INTO grants VALUES(?,?,?,?,?)',(task+'-req',task,1,mode,1))
        self.con.execute('INSERT INTO leases VALUES(?,?)',(task+'-req','closed'))

    def red(self):
        return adapter.red(self.con,self.config,self.unit,'child','red',prior_green=digest(self.prior))

    def test_real_controller_schema_normalizes_new_red_not_agent_prose(self):
        normalized=self.red()
        self.assertEqual(normalized['test_count'],2)
        self.assertEqual(normalized['task_id'],'red')
        self.assertEqual(normalized['base_manifest_sha256'],'b'*64)

    def test_old_red_cannot_be_retroactively_upgraded(self):
        del self.proof['evidence_version']
        self.con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(self.saved),))
        with self.assertRaises(ValueError):self.red()

    def test_foreign_base_changed_suite_and_missing_metadata_rejected(self):
        for key,value in [('base_manifest_sha256','a'*64),('command',['python3','partial']),('baseline_test_sha256',{})]:
            saved=copy.deepcopy(self.saved);saved['red'][key]=value
            self.con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(saved),))
            with self.assertRaises(ValueError):self.red()

    def test_worker_presence_or_old_attempt_is_not_completed_execution(self):
        self.con.execute("UPDATE leases SET status='running' WHERE request_id='red-req'")
        with self.assertRaises(ValueError):self.red()
        self.con.execute("UPDATE leases SET status='closed' WHERE request_id='red-req'")
        self.con.execute("INSERT INTO grants VALUES('unbound-new','red',2,'implementation',1)")
        with self.assertRaises(ValueError):self.red()

    def test_prior_green_must_be_real_scoped_readonly_full_suite(self):
        for key,value in [('network','host'),('snapshot_mount','rw'),('tests',0),('manifest_sha256','0'*64)]:
            receipt={**self.prior,key:value}
            self.con.execute('UPDATE review_suite_rpc SET receipt=?',(json.dumps(receipt),))
            with self.assertRaises(ValueError):
                adapter.red(self.con,self.config,self.unit,'child','red',prior_green=digest(receipt))

    def test_prior_suite_missing_native_binding_cannot_qualify(self):
        self.con.execute('DELETE FROM review_bindings')
        with self.assertRaises(ValueError):self.red()

    def test_independent_test_review_requires_current_snapshot_and_complete_reads(self):
        normalized=adapter.test_review(self.con,self.config,self.unit,'child')
        self.assertEqual(normalized['decision'],'approve')
        self.review['read_evidence']['/evidence/candidate/tests/new.py']['lines']=9
        self.con.execute('UPDATE test_revision_trials SET state=?',(json.dumps(self.review),))
        with self.assertRaises(ValueError):adapter.test_review(self.con,self.config,self.unit,'child')

    def test_stale_approval_and_own_review_cannot_qualify(self):
        self.review['manifest_sha256']='0'*64
        self.con.execute('UPDATE test_revision_trials SET state=?',(json.dumps(self.review),))
        with self.assertRaises(ValueError):adapter.test_review(self.con,self.config,self.unit,'child')
        self.review['manifest_sha256']='d'*64
        self.con.execute('UPDATE test_revision_trials SET state=?',(json.dumps(self.review),))
        self.con.execute("UPDATE native_bindings SET agent_id='author' WHERE task_id='review'")
        with self.assertRaises(ValueError):adapter.test_review(self.con,self.config,self.unit,'child')

    def green_fixture(self):
        self.bind('implement','author','implementation');self.bind('delivery-review','cto','review')
        self.unit.update(green_manifest_sha256='2'*64,green='3'*64)
        proof=dict(self.prior,evidence_version=2,source_task='implement',review_task='delivery-review',
            manifest_sha256='2'*64,base_manifest_sha256='b'*64,tests=2,
            baseline_test_sha256=self.unit['baseline_test_sha256'],new_test_sha256=self.unit['new_test_sha256'])
        self.con.execute('INSERT INTO review_suite_rpc(request_id,source_task,status,receipt) VALUES(?,?,?,?)',
            ('delivery-review-req','implement','passed',json.dumps(proof)))
        self.con.execute('INSERT INTO snapshots VALUES(?,?,?)',('implement','delivery','complete'))
        self.con.execute("UPDATE review_suite_rpc SET volume='delivery' WHERE request_id='delivery-review-req'")
        self.con.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',('delivery-review','implement','cto','2'*64,'approved'))
        return proof

    def test_green_and_delivery_review_bind_same_immutable_suite_and_snapshot(self):
        self.green_fixture()
        green=adapter.green(self.con,self.config,self.unit,'child','implement','delivery-review')
        review=adapter.delivery_review(self.con,self.config,self.unit,'child','implement','delivery-review')
        self.assertEqual(green['manifest_sha256'],review['manifest_sha256'])
        self.assertEqual(green['test_count'],2)
        self.assertEqual(review['decision'],'approve')

    def test_green_rejects_old_receipt_changed_tests_and_wrong_base(self):
        proof=self.green_fixture()
        for field,value in [('evidence_version',1),('new_test_sha256',{}),('base_manifest_sha256','0'*64)]:
            bad=dict(proof);bad[field]=value
            self.con.execute('UPDATE review_suite_rpc SET receipt=? WHERE request_id=?',
                (json.dumps(bad),'delivery-review-req'))
            with self.assertRaises(ValueError):
                adapter.green(self.con,self.config,self.unit,'child','implement','delivery-review')

    def test_delivery_approval_for_old_manifest_does_not_count(self):
        self.green_fixture()
        self.con.execute("UPDATE reviews SET manifest_sha256=?",('0'*64,))
        with self.assertRaises(ValueError):
            adapter.delivery_review(self.con,self.config,self.unit,'child','implement','delivery-review')
