import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from dependent_sequence import resume_verified_review_context
from execution_context import freeze
from portable_supervisor import stale_capsule_review_blocker


class CapsuleSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.capsule=freeze('Complete brief.','Independent review.')
        self.stage=dict(spec=dict(label='API-1',execution_context=self.capsule),contract={'exact':'contract'})
        self.plan=dict(sha256='plan',stages=[self.stage,dict(spec=dict(label='UI-1'))])
        self.context=dict(label='API-1',issue_id='issue',base_sha='b'*40,durable_handoffs=True,
            contract_sha256=hashlib.sha256(json.dumps(self.stage['contract'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            run_spec_sha256=hashlib.sha256(json.dumps(self.stage['spec'],sort_keys=True,separators=(',',':')).encode()).hexdigest())
        (self.root/'portable-context-API-1.json').write_text(json.dumps(self.context))
        self.ledger=dict(stage='blocked',plan_sha256='plan',active='API-1',completed=[],issues={'API-1':'issue'},
            category='RuntimeError:technical_decision_required:recipient_execution_failed')
        self.proof=dict(qualified=True,enabled=True,approval=False,issue_id='issue',
            contract_sha256=self.context['contract_sha256'],stage='accepted',source_task='author-task',
            source_status='completed',source_agent='author',author='author',reviewer='reviewer',cto='cto',
            request=dict(issue_id='issue',source_task='author-task',failed_review='old-review'),
            review_retries=1,baseline_tests_intact=True,cto_task='cto-task',cto_status='completed',cto_agent='cto',
            cto_wakeup='cto-wake',used=dict(cto_task='cto-task',cto_wakeup='cto-wake',
                decision=dict(action='retry_review',optional_files=[])),
            review_task='new-review',review_agent='reviewer',review_status='completed',
            review_wakeup='review-wake',wakeup='review-wake',manifest_sha256='c'*64,
            repair_context_sha256=self.capsule['sha256'],context_presentation=dict(issue_id='issue',
                task_id='new-review',agent_id='reviewer',mode='review',context_sha256=self.capsule['sha256'],delivery_approval=False))
        self.verify=Mock()

    def resume(self):
        return resume_verified_review_context(self.ledger,self.plan,self.root,
            read_proof=lambda _:self.proof,verify_initial=self.verify)

    def test_first_card_resumes_supervision_not_delivery_after_exact_base_check(self):
        result=self.resume()
        self.assertEqual(result['stage'],'working');self.assertEqual(result['completed'],[])
        self.assertEqual(result['category'],self.ledger['category'])
        self.verify.assert_called_once_with(self.context,self.stage)
        self.assertNotIn('resolved_incidents',result)

    def test_activity_without_exact_capsule_and_independent_cto_does_not_resume(self):
        for key,value in [('qualified',False),('repair_context_sha256','d'*64),
                          ('context_presentation',{}),('cto_status','running'),('review_task','old-review')]:
            old=self.proof[key];self.proof[key]=value
            self.assertIsNone(self.resume());self.proof[key]=old
        self.verify.assert_not_called()
        self.verify.side_effect=ValueError('main or CI drift')
        with self.assertRaises(ValueError): self.resume()

    def test_stale_portable_status_refresh_requires_preserved_snapshot_and_capsule(self):
        receipt=dict(operation='native_review_context_recovery_v1',approval=False,author_restarted=False,
            request=dict(issue_id='issue',source_task='source'),
            presentation=dict(operation='registered_capsule_prompt_probe_v1',context_sha256=self.capsule['sha256'],manifest_sha256='c'*64))
        data=dict(review_context_recovery=receipt,snapshot=dict(task_id='source'),evidence=dict(manifest_sha256='c'*64))
        managed=dict(route=dict(enabled=True,issue_id='issue',execution_context=self.capsule),
            state=dict(stage='accepted',source_task='source',data=json.dumps(data)))
        status=dict(stage='escalation_required',issue_id='issue',category='technical_decision_required:recipient_execution_failed')
        self.assertTrue(stale_capsule_review_blocker(status,managed))
        for key,value in [('approval',True),('author_restarted',True)]:
            receipt[key]=value;managed['state']['data']=json.dumps(data)
            self.assertFalse(stale_capsule_review_blocker(status,managed));receipt[key]=False
        managed['state']['stage']='technical_decision_required'
        self.assertFalse(stale_capsule_review_blocker(status,managed))
