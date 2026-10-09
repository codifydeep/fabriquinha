import json
import sqlite3
import unittest
from broker.bound_failure_context import project, expand, verified_failed_diagnostic


class BoundFailureContextTests(unittest.TestCase):
    def test_projection_preserves_full_failure_by_verified_reference(self):
        failure={'category':'executed_test_failure','failures':[{'qualified_name':'test_'+str(i)} for i in range(60)],'output_sha256':'a'*64}
        summary={'source_task':'source','error':'portable frozen suite failed','validation_failure':failure}
        projected,marker=project(summary,'source',failure)
        self.assertLess(len(json.dumps(projected)),700)
        self.assertEqual(projected['validation_failure']['failure_count'],60)
        note='Diagnose '+json.dumps(projected)
        row={'issue_id':'issue','data':json.dumps(dict(validation_failure=failure,target='cto',wakeup_id='wake',artifact_diagnosis=True))}
        task=dict(agent_id='cto',wakeup_id='wake')
        full=expand(note,'issue',task,lambda source:row)
        self.assertIn(json.dumps(failure,sort_keys=True,separators=(',',':')),full)
        for changed in (dict(task,agent_id='author'),dict(task,wakeup_id='old')):
            with self.assertRaises(ValueError):expand(note,'issue',changed,lambda source:row)
        failure['failures'].pop()
        with self.assertRaises(ValueError):expand(note,'issue',task,lambda source:{**row,'data':json.dumps(dict(validation_failure=failure,target='cto',wakeup_id='wake',artifact_diagnosis=True))})

    def test_marker_does_not_grant_authority_or_duplicate_expansion(self):
        failure=dict(category='executed_test_failure',failures=[])
        _,marker=project({'validation_failure':failure},'source',failure)
        with self.assertRaises(ValueError):expand(marker+'\n'+marker,'issue',{},lambda source:None)
        with self.assertRaises(ValueError):expand(marker,'issue',{},lambda source:None)
        self.assertEqual(expand('ordinary','issue',{},lambda source:self.fail()),'ordinary')

    def test_failed_transport_requires_exact_durable_diagnostic_and_snapshot(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        self.addCleanup(con.close)
        self.assertFalse(verified_failed_diagnostic(con,'source',{}))
        con.execute('CREATE TABLE failed_execution_diagnoses(source_task TEXT,receipt TEXT)')
        con.execute('CREATE TABLE failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT)')
        failure=dict(source_task='source',volume='frozen',category='executed_test_failure',
                     diagnostic_only=True,phase='failed_execution_diagnostic')
        proof=dict(request=dict(source_task='source',failure_signature='a'*64),volume='frozen',
                   failure=failure,status='diagnostic_only_not_approved')
        data=dict(failed_execution_diagnostic=proof,validation_failure=failure,source_status='failed',
                  failure_signature='a'*64,diagnostic_challenge=dict(observation='Inspect the startup hook'))
        con.execute('INSERT INTO failed_execution_diagnoses VALUES(?,?)',('source',json.dumps(proof)))
        con.execute('INSERT INTO failed_execution_snapshots VALUES(?,?,?)',('source','frozen','complete'))
        self.assertTrue(verified_failed_diagnostic(con,'source',data))
        for field,value in [('failure_signature','b'*64),('source_status','completed'),
                ('evidence',{'approved':True}),('review',{'approved':True}),('diagnostic_challenge',None)]:
            self.assertFalse(verified_failed_diagnostic(con,'source',dict(data,**{field:value})))
        con.execute("UPDATE failed_execution_snapshots SET volume='other'")
        self.assertFalse(verified_failed_diagnostic(con,'source',data))
