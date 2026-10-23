"""Failed incomplete-inspection successor; no approval or model execution."""
import copy
import json
import unittest
from unittest.mock import patch
from broker import quality_review_completion_recovery as recovery,quality_review_attestation as attest
import test_quality_review_completion_recovery as fixtures


class QualityReviewFailedRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityReviewCompletionRecoveryTests();self.f=f
        original=attest.observe
        def fail_before_observation(b,source):
            f.previous_task.update(status='failed',result=None,error='hermes session/prompt failed: Internal error',
                failure_reason='agent_error.provider_server_error')
            with b.db() as con:con.execute("UPDATE acp_events SET success=0 WHERE method='session/prompt'")
            return original(b,source)
        with patch.object(attest,'observe',side_effect=fail_before_observation):f.setUp()
        self.addCleanup(f.doCleanups);self.b=f.b
        with self.b.db() as con:
            self.removed=con.execute('SELECT task_id,request_id,call_id,messages FROM observed_read_stream ORDER BY rowid DESC LIMIT 1').fetchone()
            con.execute('DELETE FROM observed_read_stream WHERE task_id=? AND call_id=?',(self.removed[0],self.removed[2]))

    def register(self,**kwargs):
        f=self.f
        return recovery.register(self.b,f.source,f.previous_task['id'],f.operation,
            qualified=kwargs.get('qualified',f.qualified),installation=f.installation,
            failed_review=kwargs.get('failed_review',True),transport=kwargs.get('transport'))

    def test_prepares_new_review_without_reclassifying_failure_or_approving_old_reads(self):
        f=self.f;receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertEqual(receipt['diagnostic']['native_failure_cause'],'not_proven')
        self.assertEqual(receipt['diagnostic']['verdict_format'],'absent_due_to_native_failure')
        self.assertTrue(receipt['diagnostic']['reads']['rejected_files'])
        self.assertEqual(attest.load(self.b,f.source,request_id=f.request),f.old)
        self.assertIsNone(attest.load(self.b,f.source));self.assertFalse(receipt['tests_approved'])
        self.assertFalse(receipt['incident_closed']);self.assertFalse(receipt['delivery_approval'])
        self.assertTrue(recovery.activation_ready(self.b,receipt['issue_id'],f.operation))

    def test_no_generic_failed_retry_or_mixed_capacity_authority(self):
        with self.assertRaises(ValueError):self.register(failed_review=False)
        with self.assertRaises(ValueError):self.register(failed_review='true')
        with self.assertRaises(ValueError):self.register(transport={})

    def test_complete_or_invalid_read_scope_cannot_claim_incomplete_inspection(self):
        with self.b.db() as con:con.execute('INSERT INTO observed_read_stream VALUES(?,?,?,?)',tuple(self.removed))
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as con:
            con.execute('DELETE FROM observed_read_stream WHERE task_id=? AND call_id=?',(self.removed[0],self.removed[2]))
            row=con.execute('SELECT call_id,messages FROM observed_read_stream LIMIT 1').fetchone()
            pair=json.loads(row[1]);_,_,normalized=attest.reads.page(pair)
            value=json.loads(normalized[1]['output']);value['content']=value['content'].replace('1|','1|WRONG',1)
            normalized[1]['output']=json.dumps(value)
            con.execute('UPDATE observed_read_stream SET messages=? WHERE call_id=?',(json.dumps(normalized),row[0]))
        with self.assertRaises(ValueError):self.register()

    def test_same_profile_cannot_rearm_and_changed_history_is_detected(self):
        self.register();f=self.f
        q=copy.deepcopy(f.qualified);q['qualification_id']=f.next_task
        with self.assertRaises(ValueError):self.register(qualified=q)
        from broker import quality_test_review as review
        context,state=review.load(self.b,f.source)
        f.previous_task['error']='changed historical error'
        with self.assertRaises(ValueError):recovery.exclude_completed(self.b,context,state,[f.previous_task])

    def test_missing_actual_reads_cannot_be_replaced_with_native_error_or_claim(self):
        with self.b.db() as con:con.execute('DELETE FROM observed_read_stream')
        with self.assertRaises(ValueError):self.register()

    def test_same_worker_image_is_not_a_changed_condition(self):
        f=self.f
        with self.b.db() as con:
            old=json.loads(con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(f.request,)).fetchone()[0])['Image']
        f.worker=old;f.qualified['worker_image']=old
        self.b.QUALITY_WORKER_IMAGE=old;self.b.QUALITY_REVIEW_WORKER_IMAGE=old
        with self.assertRaises(ValueError):self.register()

    def test_replayed_prompt_cannot_claim_one_failed_native_execution(self):
        with self.b.db() as con:con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',
            (self.f.request,'session/prompt','duplicated',0))
        with self.assertRaises(ValueError):self.register()

    def test_successor_must_read_again_and_only_its_approval_binds_implementation(self):
        from broker import read_stream_receipts
        f=self.f;original=f.resumed
        def resumed():
            result=original();current=result[2]
            current.pop('error',None);current.pop('failure_reason',None)
            with self.b.db() as con:self.assertEqual(read_stream_receipts.load(con,current['id']),[])
            return result
        with patch.object(f,'register',side_effect=self.register),patch.object(f,'resumed',side_effect=resumed):
            f.test_valid_successor_can_freeze_exact_snapshot_without_overwriting_old_failure()
