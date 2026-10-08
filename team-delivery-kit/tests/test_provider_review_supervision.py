import tempfile
from pathlib import Path
import unittest
import test_provider_diagnosis_supervision as fixtures
from provider_review_supervision import resume, PROGRAM


class ProviderReviewSupervisionTests(unittest.TestCase):
    def test_real_new_review_resumes_observation_not_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ledger,plan,proof=fixtures.ProviderSupervisionTests().fixture(root)
            ledger['category']='RuntimeError:test_revision_blocked:invalid_independent_test_review:ValueError'
            proof['task_id']='new-review'
            got=resume(ledger,plan,root,query=lambda _:proof)
            self.assertEqual(got['stage'],'working')
            self.assertEqual(got['completed'],[])
            self.assertFalse(got['provider_review_supervision']['delivery_approval'])
            self.assertEqual(got['provider_review_supervision']['category'],ledger['category'])
            self.assertEqual(ledger['stage'],'blocked')

    def test_other_incident_or_incomplete_qualification_cannot_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ledger,plan,proof=fixtures.ProviderSupervisionTests().fixture(root)
            self.assertIsNone(resume(ledger,plan,root,query=lambda _:proof))
            ledger['category']='RuntimeError:test_revision_blocked:invalid_independent_test_review:ValueError'
            for bad in ({**proof,'qualified':False},{**proof,'delivery_approval':True},{**proof,'independent':False}):
                self.assertIsNone(resume(ledger,plan,root,query=lambda _:bad))
            compile(PROGRAM,'<readonly-review-observer>','exec')
            self.assertNotIn('UPDATE ',PROGRAM)
