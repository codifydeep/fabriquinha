import copy
import json
import unittest
from broker.technical_replan_certificate import qualify
from portable_test_revision_recovery import next_revision_depth


class TechnicalReplanCertificateTests(unittest.TestCase):
    def setUp(self):
        self.route=dict(issue_id='issue',author='author',cto='cto',test_first=True,test_first_files=['tests/test_new.py'])
        self.data=dict(source_task='source',target='cto',recipient_task='decision',wakeup_id='wake',
            validation_failure=dict(category='executed_test_failure',phase='frozen_green',source_task='source',
                exit_code=1,tests_executed=323,failures=[dict(test='test_pending')],output_sha256='a'*64,
                diagnostic_read_files=['app/client.js']),
            phase_evidence=dict(phase='implementation',independent_test_review='approved',red_manifest='b'*64,
                frozen_test_hashes={'tests/test_new.py':'c'*64}))
        self.task=dict(id='decision',status='completed',agent_id='cto',issue_id='issue',wakeup_id='wake')
        self.decision=dict(action='request_test_revision',reason='Repair the observed harness schedule',optional_files=[])
        self.reads={p:dict(lines=10,total_lines=10) for p in ('/evidence/candidate/tests/test_new.py','/evidence/candidate/app/client.js')}

    def certificate(self):return qualify(self.route,self.data,self.task,self.decision,self.reads)

    def test_actual_replan_authorizes_one_extra_depth_not_delivery(self):
        before=copy.deepcopy(self.data);proof=self.certificate();self.assertEqual(before,self.data)
        data={**self.data,'technical_replan_certificate':proof,'test_revision_proposal':dict(
            decision_task='decision',source_task='source',output_sha256='a'*64)}
        managed=dict(state=dict(source_task='source',data=json.dumps(data)))
        self.assertEqual(next_revision_depth(dict(issue_id='issue'),managed,'1'),'2')
        with self.assertRaises(ValueError):next_revision_depth(dict(issue_id='issue'),managed,'2')
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['baseline_edits_allowed'])

    def test_source_bound_certificate_resumes_only_matching_blocked_projection(self):
        from pre_red_supervision import qualified
        proof=self.certificate()
        data={**self.data,'technical_replan_certificate':proof,'test_revision_proposal':dict(
            decision_task='decision',source_task='source',output_sha256='a'*64)}
        managed=dict(route={**self.route,'enabled':True},state=dict(
            source_task='source',stage='test_revision_required',data=json.dumps(data)))
        status=dict(issue_id='issue',stage='escalation_required',category=
            'test_revision_recovery:ValueError:second test revision requires new technical replan')
        context=dict(issue_id='issue',contract_sha256='contract')
        observed=dict(qualified=True,independent=True,managed=managed,issue_id='issue',
            contract_sha256='contract',delivery_approval=False,author_retry_authorized=False)
        self.assertTrue(qualified(status,context,query=lambda _:observed))
        self.assertFalse(qualified(status,context,query=lambda _:{**observed,'qualified':False}))
        proof['source_task']='old'
        managed['state']['data']=json.dumps(data)
        self.assertFalse(qualified(status,context,query=lambda _:observed))

    def test_read_task_failure_and_frozen_hash_drift_fail_closed(self):
        for target,key,value in ((self.task,'agent_id','author'),(self.task,'status','failed'),
            (self.task,'wakeup_id','old'),(self.task,'issue_id','other'),
            (self.data['validation_failure'],'source_task','old'),
            (self.data['validation_failure'],'phase','unexecuted'),
            (self.data['validation_failure'],'tests_executed',0),
            (self.data['phase_evidence'],'frozen_test_hashes',{}),
            (self.decision,'action','approve'),
            (self.reads['/evidence/candidate/app/client.js'],'lines',9)):
            old=target[key];target[key]=value
            with self.assertRaises(ValueError):self.certificate()
            target[key]=old
