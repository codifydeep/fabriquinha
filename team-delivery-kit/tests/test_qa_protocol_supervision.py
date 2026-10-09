import tempfile
from pathlib import Path
import unittest
import test_provider_diagnosis_supervision as fixtures
from qa_protocol_supervision import resume


class QaProtocolSupervisionTests(unittest.TestCase):
    def test_only_pinned_blocked_sequence_resumes_observation_not_author(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ledger,plan,proof=fixtures.ProviderSupervisionTests().fixture(root)
            ledger['category']='RuntimeError:ValueError:QA issue metadata drift: execution_gate'
            result=resume(ledger,plan,root,None,query=lambda _:proof)
            self.assertEqual(result['stage'],'working')
            self.assertEqual(result['completed'],[])
            self.assertEqual(ledger['stage'],'blocked')
            self.assertIs(result['qa_protocol_supervision']['delivery_approval'],False)
            for invalid in ({**proof,'author_retry_authorized':True},
                            {**proof,'delivery_approval':True},{**proof,'independent':False}):
                self.assertIsNone(resume(ledger,plan,root,None,query=lambda _:invalid))

    def test_other_incident_or_plan_drift_cannot_trigger_a_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ledger,plan,proof=fixtures.ProviderSupervisionTests().fixture(root)
            self.assertIsNone(resume(ledger,plan,root,None,query=lambda _:self.fail('wrong incident')))
            ledger['category']='RuntimeError:delivery_incomplete'
            plan['stages'][0]['contract']={'changed':True}
            self.assertIsNone(resume(ledger,plan,root,None,query=lambda _:self.fail('changed plan')))
