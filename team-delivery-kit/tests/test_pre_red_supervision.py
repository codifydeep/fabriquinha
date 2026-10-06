import hashlib
import json
import unittest
from pre_red_supervision import eligible,qualified


class PreRedSupervisionTests(unittest.TestCase):
    def test_capacity_receipt_only_resumes_matching_snapshot_observation(self):
        data=json.loads(self.managed['state']['data']);data.pop('diagnostic_presentation_recovery')
        data['read_capacity_diagnosis']=dict(operation='read_capacity_diagnosis_v1',
            issue_id='issue',source_task='author',author_retry_authorized=False,delivery_approval=False,
            probe=dict(baseline_unchanged=True,all_lines_observed=True,manifest_sha256='a'*64))
        self.managed['state']['data']=json.dumps(data)
        self.assertTrue(eligible(self.status,self.managed))
        data['read_capacity_diagnosis']['probe']['manifest_sha256']='different'
        self.managed['state']['data']=json.dumps(data)
        self.assertFalse(eligible(self.status,self.managed))
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
