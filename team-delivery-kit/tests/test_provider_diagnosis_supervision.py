import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from provider_diagnosis_supervision import resume


class ProviderSupervisionTests(unittest.TestCase):
    def fixture(self,root):
        contract={'example':'pinned'};spec={'label':'FIRST','objective':'unchanged'}
        context={'issue_id':'issue','label':'FIRST','durable_handoffs':True,
            'contract_sha256':hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'run_spec_sha256':hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        (root/'portable-context-FIRST.json').write_text(json.dumps(context))
        ledger={'stage':'blocked','category':'RuntimeError:test_first_blocked:test_first_cto_execution_failed',
                'active':'FIRST','completed':[],'plan_sha256':'plan','issues':{'FIRST':'issue'}}
        plan={'sha256':'plan','stages':[{'contract':contract,'spec':spec}]}
        proof={'qualified':True,'issue_id':'issue','contract_sha256':context['contract_sha256'],
               'independent':True,'recovery_sha256':'a'*64,'task_id':'cto-new',
               'delivery_approval':False,'author_retry_authorized':False}
        return ledger,plan,proof

    def test_first_stage_can_resume_observation_not_become_done(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ledger,plan,proof=self.fixture(root)
            got=resume(ledger,plan,root,query=lambda _:proof)
            self.assertEqual(got['stage'],'working');self.assertEqual(got['completed'],[])
            self.assertNotIn('category',got)
            self.assertEqual(got['provider_diagnosis_supervision']['category'],ledger['category'])
            self.assertEqual(ledger['stage'],'blocked')

    def test_no_receipt_wrong_contract_or_approval_does_not_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ledger,plan,proof=self.fixture(root)
            for bad in ({}, {**proof,'qualified':False},{**proof,'contract_sha256':'other'},
                        {**proof,'delivery_approval':True},{**proof,'author_retry_authorized':True},
                        {**proof,'independent':False}):
                self.assertIsNone(resume(ledger,plan,root,query=lambda _:bad))
            plan['stages'][0]['spec']['objective']='changed'
            self.assertIsNone(resume(ledger,plan,root,query=lambda _:proof))
