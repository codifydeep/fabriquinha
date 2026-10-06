import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from citation_supervision import TEST_CATEGORY, eligible, resume


class CitationSupervisionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.stage=dict(spec=dict(label='UI'),contract={'review':'independent'})
        self.plan=dict(sha256='plan',stages=[self.stage])
        digest=hashlib.sha256(json.dumps(self.stage['contract'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.context=dict(issue_id='issue',label='UI',contract_sha256=digest,durable_handoffs=True)
        (self.root/'portable-context-UI.json').write_text(json.dumps(self.context))
        self.ledger=dict(stage='blocked',active='UI',completed=[],issues={'UI':'issue'},
                         plan_sha256='plan',category='RuntimeError:'+TEST_CATEGORY)
        self.proof=dict(qualified=True,enabled=True,issue_id='issue',contract_sha256=digest,
            independent=True,source_status='completed',source_task='author',approval=False,
            author_restarted=False,review_task='fresh-review',review_status='running',
            review_wakeup='wake',wakeup='wake',state_status='awaiting_review',
            manifest_sha256='a'*64,frozen_manifest='a'*64,candidate_volume='frozen',frozen_volume='frozen')
        self.verify=Mock()

    def run_resume(self):
        return resume(self.ledger,self.plan,self.root,query=lambda _:self.proof,verify_initial=self.verify)

    def test_reentry_preserves_incident_and_never_completes_delivery(self):
        before=copy.deepcopy(self.ledger)
        result=self.run_resume()
        self.assertEqual(result['stage'],'working')
        self.assertEqual(result['completed'],[])
        self.assertEqual(result['category'],before['category'])
        self.assertEqual(self.ledger,before)
        self.verify.assert_called_once_with(self.context,self.stage)
        self.assertEqual(result['recovery_supervision'][0]['status'],'supervision_resumed_not_delivered')

    def test_unqualified_identity_artifacts_and_failed_retry_do_not_resume(self):
        for key,value in [('qualified',False),('enabled',False),('issue_id','other'),
                ('contract_sha256','other'),('independent',False),('source_status','running'),
                ('approval',True),('author_restarted',True),('review_task','author'),
                ('review_status','failed'),('review_wakeup','old'),('manifest_sha256','b'*64),
                ('candidate_volume','mutable'),('state_status','blocked')]:
            with self.subTest(key=key):
                old=self.proof[key];self.proof[key]=value
                self.assertIsNone(self.run_resume());self.proof[key]=old
        self.verify.assert_not_called()
        self.proof.update(state_status='blocked',decision=None)
        self.assertIsNone(self.run_resume())
        self.proof['decision']={'action':'reject_test_revision'}
        self.assertEqual(self.run_resume()['stage'],'working')
        self.verify.side_effect=ValueError('base CI drift')
        with self.assertRaises(ValueError):self.run_resume()

    def test_successor_requires_exact_predecessor_and_live_qa_ci(self):
        prior=dict(spec=dict(label='API'))
        self.plan['stages'].insert(0,prior);self.ledger['completed']=['API']
        self.context['base_sha']='b'*40
        (self.root/'portable-context-UI.json').write_text(json.dumps(self.context))
        qa=Mock();ci=Mock()
        with unittest.mock.patch('dependent_sequence.receipt_identity',return_value=True):
            kwargs=dict(query=lambda _:self.proof,read_delivery=lambda *_:{'merge_sha':'b'*40},verify=qa,verify_ci=ci)
            result=resume(self.ledger,self.plan,self.root,**kwargs)
            self.assertEqual(result['completed'],['API']);qa.assert_called_once();ci.assert_called_once()
            kwargs['read_delivery']=lambda *_:{'merge_sha':'c'*40}
            self.assertIsNone(resume(self.ledger,self.plan,self.root,**kwargs))

    def test_projection_requires_preserved_same_source_and_snapshot(self):
        repair=dict(approval=False,author_restarted=False,attempt_limit=1,failed_task='old',
            prior_state=dict(source_task='author',manifest_sha256='a'*64,candidate_volume='frozen',
                review_failure={'detail':'finding quote not observed at exact line'}))
        data=dict(citation_recovery=repair,manifest_sha256='a'*64,candidate_volume='frozen')
        managed=dict(route=dict(enabled=True,issue_id='issue'),state=dict(
            stage='awaiting_test_revision_review',source_task='author',data=json.dumps(data)))
        status=dict(stage='escalation_required',category=TEST_CATEGORY,issue_id='issue')
        self.assertTrue(eligible(status,managed))
        repair['approval']=True;managed['state']['data']=json.dumps(data)
        self.assertFalse(eligible(status,managed))
