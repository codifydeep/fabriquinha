import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import portable_qa_observation as q
from release_eval import save_receipt


class ObservationRecoveryTests(unittest.TestCase):
    def setUp(self):
        authority = patch('portable_qa_authority.recover', return_value=None)
        authority.start(); self.addCleanup(authority.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.incident = {'key':'a'*16,'phase':'browser','label':'DETAIL-1',
                         'parent_issue_id':'parent','source_sha':'b'*40}
        self.config = {'scenario':'feedback-board-detail-ui-v1','browser_image':'sha256:'+'c'*64}
        self.identity = {'config':self.config,'source_sha':'b'*40,'application_image':'sha256:'+'d'*64,
                         'deployed_container_id':'e'*64,'runtime_env':{'FEEDBACK_DB_PATH':'/tmp/feedback.db'},
                         'scenario_sha256':'f'*64}
        self.old = {'identity':self.identity,'status':'failed','cleanup':'passed',
                    'automated':True,'error':'selector failed'}
        self.prior = {'cto_id':'cto','child_issue_id':'prior-cto'}
        self.observed = {'task_id':'previous-task','issue_id':'prior-cto',
                         'decision_sha256':'1'*64,'browser_receipt':self.old}
        from portable_browser_qa import script_for
        self.new = {**self.old,'error':'HTTP 400 at /feedback?status=open?q=needle',
                    'identity':{**self.identity,'scenario_sha256':hashlib.sha256(
                        script_for(self.config).read_bytes()).hexdigest()}}
        self.path = self.root/'browser-acceptance/DETAIL-1'/('2'*64+'.json')
        self.path.parent.mkdir(parents=True)
        save_receipt(self.path,self.new)
        save_receipt(self.root/'release-receipts/DETAIL-1.json',
                     {'issue_id':'parent','merge_sha':'b'*40,
                      'deployment':{'source_sha':'b'*40,'image_id':'sha256:'+'d'*64}})

    def recover(self, **overrides):
        args = dict(incident=self.incident,prior=self.prior,parent_contract={},
                    budget_ready=True,observe=lambda *_:self.observed)
        args.update(overrides)
        return q.recover(self.root,None,**args)

    def test_new_failed_observation_grants_diagnosis_only_and_preserves_old(self):
        before = json.dumps(self.old,sort_keys=True)
        with patch('portable_qa_cto.record',return_value={'dispatch':'cto_started'}) as record:
            self.assertEqual(self.recover(),{'dispatch':'cto_started'})
            proof = record.call_args.kwargs['observation_recovery']
            q.validate(self.root,self.incident,proof)
            self.assertIs(proof['delivery_approval'],False)
            self.assertIs(proof['author_retry_authorized'],False)
            self.assertEqual(proof['previous']['task_id'],'previous-task')
            self.assertEqual(json.dumps(self.old,sort_keys=True),before)
            self.recover()
            self.assertEqual(record.call_args.kwargs['observation_recovery'],proof)

    def test_changed_product_or_cleanup_is_not_a_diagnostic_recovery(self):
        for key,value in [('application_image','sha256:'+'9'*64),('deployed_container_id','9'*64)]:
            save_receipt(self.path,{**self.new,'identity':{**self.new['identity'],key:value}})
            with self.assertRaisesRegex(ValueError,'changed product'):self.recover()
        save_receipt(self.path,{**self.new,'cleanup':'failed'})
        with patch('portable_qa_cto.record') as record:
            self.assertIsNone(self.recover());record.assert_not_called()

    def test_same_recipe_passed_recipe_and_pending_diagnosis_cannot_dispatch(self):
        with patch('portable_qa_cto.record') as record:
            self.assertIsNone(self.recover(observe=lambda *_:None))
            self.assertIsNone(self.recover(budget_ready=False,
                                          observe=lambda *_:self.fail('no calls')))
            save_receipt(self.path,{**self.new,'status':'passed'})
            self.assertIsNone(self.recover())
            save_receipt(self.path,self.old)
            self.assertIsNone(self.recover())
            record.assert_not_called()

    def test_observation_drift_after_dispatch_never_grants_another_attempt(self):
        with patch('portable_qa_cto.record',return_value={}):self.recover()
        save_receipt(self.path,{**self.new,'error':'changed error'})
        with patch('portable_qa_cto.record') as record:
            with self.assertRaisesRegex(ValueError,'one observation recovery'):self.recover()
            record.assert_not_called()

    def test_ambiguous_receipts_fail_closed(self):
        save_receipt(self.path.with_name('3'*64+'.json'),self.new)
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.recover()

    def test_unsafe_receipt_cannot_start_a_diagnosis(self):
        self.path.unlink(); self.path.symlink_to(self.root/'release-receipts/DETAIL-1.json')
        with self.assertRaisesRegex(ValueError,'safe protocol recovery receipt'):self.recover()

    def test_real_record_dispatches_once_and_never_rebinds_executed_diagnosis(self):
        from test_portable_qa_cto import Board
        from portable_qa_cto import record
        board = Board()
        incident = {**self.incident, 'child_issue_id':'diagnosis',
                    'category':'post-deploy browser QA fixture failed'}
        proof = {'incident_key':incident['key'],'source_sha':incident['source_sha'],
                 'cto_id':'cto-agent','previous':self.observed,
                 'current':q.current(self.root,incident,self.old),
                 'delivery_approval':False,'author_retry_authorized':False}
        save_receipt(self.root/'qa-observation-proofs'/(incident['key']+'.json'),proof)
        contract = {'editable_files':['static/app.js'],'test_files':[],'test_roots':['tests']}
        args = dict(incident=incident,parent_contract=contract,cto_id='cto-agent',
                    reason='New evidence',budget_ready=True,observation_recovery=proof)
        with patch('portable_qa_evidence.bind') as bind:
            first = record(self.root,board,**args)
            second = record(self.root,board,**args)
            self.assertEqual(first,second)
            self.assertEqual(board.starts,1)
            self.assertEqual(bind.call_count,1)
            self.assertEqual(board.cards['cto']['title'],'QA-CTO-AAAAAAAA-O1')
            self.assertEqual(board.cards['diagnosis']['metadata']['qa_cto_observation_issue_id'],'cto')
        board.runs[0]['status']='failed'
        with patch('portable_qa_evidence.bind') as bind:
            self.assertEqual(record(self.root,board,**args)['dispatch'],'cto_failed')
            bind.assert_not_called()
            self.assertEqual(board.starts,1)
