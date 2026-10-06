import hashlib
import json
import unittest
from pre_red_supervision import eligible,qualified,resumed_projection


class PreRedSupervisionTests(unittest.TestCase):
    def test_resumed_projection_preserves_history_without_reporting_stale_block(self):
        previous=dict(stage='blocked',category='RuntimeError:delivery_incomplete',owner='cto',
            next_action='Inspect',board_notification_error='old',active='card',completed=['predecessor'])
        result=resumed_projection(previous,'child')
        self.assertEqual(previous['stage'],'blocked')
        self.assertEqual(result['stage'],'working');self.assertEqual(result['active'],'card')
        self.assertEqual(result['completed'],['predecessor'])
        self.assertFalse(result['pre_red_supervision_recovery']['delivery_approval'])
        self.assertEqual(result['pre_red_supervision_recovery']['category'],previous['category'])
        for key in ('category','owner','next_action','board_notification_error'):self.assertNotIn(key,result)
    def test_completed_review_can_resume_observation_without_catching_transient_wait(self):
        data=dict(source_task='author',status='approved',manifest_sha256='a'*64,
            review_task='review',read_contract='complete-lines-v2',
            decision=dict(action='approve_test_revision',manifest_sha256='a'*64))
        managed=dict(route=self.managed['route'],state=dict(source_task='author',
            stage='test_revision_approved',data=json.dumps(data)),
            failed_test_checkpoint=dict(operation='failed_test_checkpoint_v1',status='red_captured',
                issue_id='issue',source_task='author',delivery_approved=False,native_task_completed=False))
        stale={**self.status,'category':'test_first_blocked:test_first_correction_failed_after_cto_diagnosis'}
        self.assertTrue(eligible(stale,managed))
        for key,value in (('read_contract','legacy'),('review_task',None),('status','blocked')):
            changed={**data,key:value};managed['state']['data']=json.dumps(changed)
            self.assertFalse(eligible(stale,managed))
        data['decision']['manifest_sha256']='b'*64
        managed['state']['data']=json.dumps(data)
        self.assertFalse(eligible(stale,managed))
    def test_failed_checkpoint_resumes_review_observation_only(self):
        data=dict(source_task='author',status='awaiting_review',manifest_sha256='a'*64)
        managed=dict(route=self.managed['route'],state=dict(source_task='author',
            stage='awaiting_test_revision_review',data=json.dumps(data)),
            failed_test_checkpoint=dict(operation='failed_test_checkpoint_v1',status='red_captured',
                issue_id='issue',source_task='author',delivery_approved=False,native_task_completed=False))
        stale={**self.status,'category':'test_first_blocked:test_first_correction_failed_after_cto_diagnosis'}
        proof=dict(qualified=True,independent=True,issue_id='issue',contract_sha256='hash',
            delivery_approval=False,author_retry_authorized=False,managed=managed)
        self.assertTrue(qualified(stale,dict(issue_id='issue',contract_sha256='hash'),query=lambda _:proof))
        managed['failed_test_checkpoint']['native_task_completed']=True
        self.assertFalse(eligible(stale,managed))
        managed['failed_test_checkpoint']['native_task_completed']=False
        managed['state']['stage']='test_revision_blocked'
        self.assertFalse(eligible(stale,managed))
    def test_capacity_receipt_only_resumes_matching_snapshot_observation(self):
        data=json.loads(self.managed['state']['data']);data.pop('diagnostic_presentation_recovery')
        data['read_capacity_diagnosis']=dict(operation='read_capacity_diagnosis_v1',
            issue_id='issue',source_task='author',author_retry_authorized=False,delivery_approval=False,
            probe=dict(baseline_unchanged=True,all_lines_observed=True,manifest_sha256='a'*64))
        self.managed['state']['data']=json.dumps(data)
        self.assertTrue(eligible(self.status,self.managed))
        stale={**self.status,'category':'test_first_blocked:test_first_correction_failed_after_cto_diagnosis'}
        self.assertTrue(eligible(stale,self.managed))
        data['read_capacity_diagnosis']['probe']['manifest_sha256']='different'
        self.managed['state']['data']=json.dumps(data)
        self.assertFalse(eligible(self.status,self.managed))
        self.assertFalse(eligible(stale,self.managed))

    def test_generic_blocked_projection_cannot_resume_without_capacity_certificate(self):
        stale={**self.status,'category':'test_first_blocked:test_first_correction_failed_after_cto_diagnosis'}
        self.assertFalse(eligible(stale,self.managed))
    def test_postwrite_diagnosis_reentry_requires_matching_preserved_snapshot(self):
        data=json.loads(self.managed['state']['data']);data.pop('diagnostic_presentation_recovery')
        data['diagnostic']['manifest_sha256']='hash'
        data['postwrite_diagnosis']=dict(operation='postwrite_phase_diagnosis_v1',
            source_task='author',issue_id='issue',author_retry_authorized=False,delivery_approval=False,
            probe=dict(verified=True,baseline_unchanged=True,manifest_sha256='hash'))
        self.managed['state']['data']=json.dumps(data)
        self.assertTrue(eligible(self.status,self.managed))
        data['postwrite_diagnosis']['probe']['manifest_sha256']='other'
        self.managed['state']['data']=json.dumps(data)
        self.assertFalse(eligible(self.status,self.managed))

    def setUp(self):
        diagnostic={'kind':'rejected_red','manifest_sha256':'a'*64}
        data={'phase':'test_first','diagnostic':diagnostic,'test_first_cto_wakeup':'wake',
              'diagnostic_presentation_recovery':{'operation':'bounded_pre_red_diagnostic_presentation_v1',
                  'source_task':'author','diagnostic_sha256':hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),
                  'approval':False,'author_restarted':False}}
        self.managed={'route':{'enabled':True,'issue_id':'issue'},
                      'state':{'stage':'test_first_cto_diagnosis','source_task':'author','data':json.dumps(data)}}
        self.status={'stage':'escalation_required','category':'technical_decision_required:unchanged','issue_id':'issue'}

    def test_exact_receipt_can_resume_observation_not_approval(self):
        self.assertTrue(eligible(self.status,self.managed))
        proof={'qualified':True,'independent':True,'issue_id':'issue','contract_sha256':'hash',
               'delivery_approval':False,'author_retry_authorized':False,'managed':self.managed}
        context={'issue_id':'issue','contract_sha256':'hash'}
        self.assertTrue(qualified(self.status,context,query=lambda _:proof))
        self.assertFalse(qualified(self.status,context,query=lambda _:{**proof,'qualified':False}))
        self.assertFalse(qualified(self.status,context,query=lambda _:{**proof,'independent':False}))

    def test_changed_diagnostic_or_blocked_native_stage_cannot_resume(self):
        data=json.loads(self.managed['state']['data']);data['diagnostic']['kind']='changed'
        self.managed['state']['data']=json.dumps(data)
        self.assertFalse(eligible(self.status,self.managed))
        self.managed['state']['stage']='test_first_blocked'
        self.assertFalse(eligible(self.status,self.managed))

    def test_other_terminal_status_does_not_query_or_restart(self):
        def forbidden(_):raise AssertionError('unexpected query')
        self.assertFalse(qualified({**self.status,'category':'unknown'}, {},query=forbidden))


if __name__=='__main__':unittest.main()
