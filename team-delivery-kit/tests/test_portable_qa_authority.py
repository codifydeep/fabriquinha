import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qa_decision_authority import CONTRACT, VERSION, self_referral
import portable_qa_authority as q
from release_eval import save_receipt


class AuthorityTests(unittest.TestCase):
    def test_self_referral_is_not_an_approval_or_a_generic_blocked_detector(self):
        decision={'decision':'blocked','root_cause':'Blocked pending CTO authorization of repair',
                  'editable_code_files':[],'new_test_file':'','acceptance':[]}
        self.assertTrue(self_referral(decision))
        for invalid in ({**decision,'decision':'repair'},
                        {**decision,'root_cause':'Need user decision on the feature'},
                        {**decision,'root_cause':'Infrastructure unavailable'},
                        {**decision,'editable_code_files':['app.py']},
                        {**decision,'root_cause':'CTO approved the fix'}):
            self.assertFalse(self_referral(invalid))

    def fixture(self):
        incident={'key':'a'*16,'phase':'browser','source_sha':'b'*40,
                  'child_issue_id':'diagnosis','category':'post-deploy browser QA failed'}
        prior={'cto_id':'cto-agent','child_issue_id':'previous'}
        old={'task_id':'old-task','issue_id':'previous','decision_sha256':'c'*64,
             'browser_receipt':{'identity':{'source_sha':'b'*40}}}
        return incident,prior,old

    def test_one_clarification_preserves_failure_and_never_rebinds_or_respawns(self):
        from portable_qa_cto import record
        from test_portable_qa_cto import Board
        with tempfile.TemporaryDirectory() as folder:
            incident,prior,old=self.fixture();board=Board()
            contract={'editable_files':['app.py'],'test_files':[],'test_roots':['tests']}
            args=dict(incident=incident,prior=prior,parent_contract=contract,budget_ready=True,
                      observe=lambda *_:old)
            with patch('portable_qa_evidence.bind') as bind:
                first=q.recover(folder,board,**args)
                second=q.recover(folder,board,**args)
                self.assertEqual(first,second)
                self.assertEqual(board.starts,1);self.assertEqual(bind.call_count,1)
                self.assertEqual(first['title'],'QA-CTO-AAAAAAAA-D1')
                self.assertEqual(first['decision_contract_version'],VERSION)
                proof=first['authority_recovery'];q.validate(folder,incident,proof)
                self.assertIs(proof['delivery_approval'],False)
                self.assertIs(proof['author_retry_authorized'],False)
                self.assertEqual(proof['previous']['task_id'],'old-task')
            board.runs[0]['status']='failed'
            with patch('portable_qa_evidence.bind') as bind:
                self.assertEqual(q.recover(folder,board,**args)['dispatch'],'cto_failed')
                self.assertEqual(board.starts,1);bind.assert_not_called()
            with self.assertRaisesRegex(ValueError,'one authority clarification'):
                q.recover(folder,board,**{**args,'observe':lambda *_:{**old,'task_id':'other'}})

    def test_budget_or_no_protocol_error_never_starts_a_task(self):
        incident,prior,old=self.fixture()
        with tempfile.TemporaryDirectory() as folder,patch('portable_qa_cto.record') as record:
            args=dict(incident=incident,prior=prior,parent_contract={},budget_ready=False,
                      observe=lambda *_:self.fail('no work'))
            self.assertIsNone(q.recover(folder,None,**args))
            self.assertIsNone(q.recover(folder,None,**{**args,'budget_ready':True,'observe':lambda *_:None}))
            record.assert_not_called()

    def test_policy_drift_and_approval_flags_fail_closed(self):
        incident,prior,old=self.fixture()
        with tempfile.TemporaryDirectory() as folder,patch('portable_qa_cto.record',return_value={}):
            q.recover(folder,None,incident=incident,prior=prior,parent_contract={},
                      budget_ready=True,observe=lambda *_:old)
            path=Path(folder)/'qa-authority-proofs'/(incident['key']+'.json')
            proof=json.loads(path.read_text())
            for field,value in [('delivery_approval',True),('author_retry_authorized',True),
                                ('contract_version',1),('contract_sha256','d'*64)]:
                changed={**proof,field:value};save_receipt(path,changed)
                with self.assertRaisesRegex(ValueError,'non-authorizing'):q.validate(folder,incident,changed)

    def test_old_card_contract_remains_frozen_new_cards_explain_proposal_authority(self):
        from portable_qa_cto import record
        from test_portable_qa_cto import Board
        incident,prior,old=self.fixture();board=Board()
        contract={'editable_files':['app.py'],'test_files':[],'test_roots':['tests']}
        with tempfile.TemporaryDirectory() as folder,patch('portable_qa_evidence.bind'):
            args=dict(incident=incident,parent_contract=contract,cto_id='cto-agent',
                      reason='Technical diagnosis',budget_ready=False)
            first=record(folder,board,**args)
            self.assertEqual(first['decision_contract_version'],2)
            path=Path(folder)/'qa-cto-escalations'/(incident['key']+'.json')
            old_receipt={k:v for k,v in first.items() if k!='decision_contract_version'}
            save_receipt(path,old_receipt)
            self.assertEqual(record(folder,board,**args),old_receipt)
            self.assertIn('a scoped PROPOSAL',CONTRACT)
            self.assertIn('not required or allowed to edit',CONTRACT)
