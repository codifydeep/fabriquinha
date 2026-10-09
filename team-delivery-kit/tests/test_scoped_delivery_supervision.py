import tempfile
from pathlib import Path
import unittest
import test_provider_diagnosis_supervision as fixtures
from scoped_delivery_supervision import resume, eligible, PROGRAM


class ScopedDeliverySupervisionTests(unittest.TestCase):
    def test_qualified_delivery_resumes_observer_not_delivery_or_author(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ledger,plan,proof=fixtures.ProviderSupervisionTests().fixture(root)
            ledger['category']='RuntimeError:technical_decision_required:portable frozen suite failed'
            result=resume(ledger,plan,root,query=lambda _:proof)
            self.assertEqual(result['stage'],'working')
            self.assertEqual(result['completed'],[])
            self.assertFalse(result['scoped_delivery_supervision']['delivery_approval'])
            self.assertEqual(ledger['stage'],'blocked')
            self.assertEqual(result['scoped_delivery_supervision']['category'],ledger['category'])

    def test_unqualified_or_wrong_identity_cannot_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ledger,plan,proof=fixtures.ProviderSupervisionTests().fixture(root)
            self.assertIsNone(resume(ledger,plan,root,query=lambda _:proof))
            ledger['category']='RuntimeError:technical_decision_required:portable frozen suite failed'
            for change in ({'qualified':False},{'independent':False},{'delivery_approval':True},
                           {'author_retry_authorized':True},{'issue_id':'other'},
                           {'contract_sha256':'other'},{'recovery_sha256':''}):
                self.assertIsNone(resume(ledger,plan,root,query=lambda _:{**proof,**change}))

    def test_supervisor_requires_exact_context_and_qualified_proof(self):
        context=dict(issue_id='issue',contract_sha256='contract',durable_handoffs=True)
        status=dict(issue_id='issue',stage='escalation_required',
                    category='technical_decision_required:portable frozen suite failed')
        proof=dict(qualified=True,independent=True,issue_id='issue',contract_sha256='contract',
                   task_id='task',recovery_sha256='a'*64,delivery_approval=False,author_retry_authorized=False)
        self.assertTrue(eligible(status,context,query=lambda _:proof))
        for change in ({'qualified':False},{'issue_id':'other'},{'delivery_approval':True},
                       {'author_retry_authorized':True},{'task_id':''},{'recovery_sha256':'bad'}):
            self.assertFalse(eligible(status,context,query=lambda _:{**proof,**change}))
        self.assertFalse(eligible({**status,'category':'other'},context,query=lambda _:proof))
        compile(PROGRAM,'<readonly-scoped-delivery>','exec')
        self.assertIn('p.qualified(b,issue,delivery)',PROGRAM)
        self.assertNotIn('UPDATE ',PROGRAM)
