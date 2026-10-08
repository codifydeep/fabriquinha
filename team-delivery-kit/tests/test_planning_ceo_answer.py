import copy
import unittest
from planning_ceo_answer import make_answer, resume, context, pending


class CEOAnswerTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(name='DEMO-2', stage='blocked_awaiting_ceo', owner='ceo',
            brief_sha256='a'*64, configuration_sha256='b'*64, base_sha='c'*40,
            questions=['Should all non-demo modes show unavailable?'],
            issues={'product':'issue-original'}, outputs={'product':dict(task_id='task-original',
                proposal=dict(role='product',stories=[dict(title='Mode',acceptance=['Demo shown'])],
                              business_questions=['Should all non-demo modes show unavailable?']))})
        self.answer='Yes. Every response other than {"mode":"demo"} shows "Environment unavailable".'

    def test_answer_resumes_only_its_question_and_preserves_prior_evidence(self):
        before=copy.deepcopy(self.state)
        receipt=make_answer(self.state,self.answer,'direct CEO reply in Codex')
        result=resume(self.state,receipt)
        self.assertEqual(self.state,before)
        self.assertEqual(result['stage'],'resuming_product_after_ceo')
        self.assertEqual(result['outputs'],{})
        self.assertEqual(result['prior_ceo_question']['output'],before['outputs']['product'])
        self.assertEqual(result['ceo_answer']['answer'],self.answer)
        self.assertEqual(result['brief_sha256'],before['brief_sha256'])
        for key in ('authorizes_merge','authorizes_tools','waives_security','approves_brief'):
            self.assertIs(receipt[key],False)
        self.assertIsNone(resume(result,receipt))

    def test_drift_and_expanded_authority_are_rejected(self):
        receipt=make_answer(self.state,self.answer,'direct CEO reply')
        for field in ('name','brief_sha256','configuration_sha256','base_sha','question_sha256','issue_id'):
            changed={**receipt,field:'different'}
            with self.subTest(field=field),self.assertRaises(ValueError):resume(self.state,changed)
        for field in ('authorizes_merge','authorizes_tools','waives_security','approves_brief'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                resume(self.state,{**receipt,field:True})
        with self.assertRaises(ValueError):resume(self.state,{**receipt,'extra':'permission'})

    def test_different_question_is_not_implicitly_answered(self):
        receipt=make_answer(self.state,self.answer,'direct CEO reply')
        changed=copy.deepcopy(self.state);changed['questions']=['A new question?']
        with self.assertRaises(ValueError):resume(changed,receipt)
        for stage in ('plan_ready','blocked','working_product'):
            with self.assertRaises(ValueError):make_answer({**self.state,'stage':stage},self.answer,'reply')

    def reviewed_state(self):
        state=copy.deepcopy(self.state)
        state['prior_source_review_product']={'output':copy.deepcopy(state['outputs']['product']),
            'issue_id':state['issues']['product'],'questions':state['questions'][:]}
        state['outputs']['product']['task_id']='task-later'
        state['outputs']['product']['proposal']['business_questions']=['Later differently worded question?']
        state['issues']['product']='issue-later'
        state['source_review']={'stage':'verified','brief_sha256':state['brief_sha256'],
            'configuration_sha256':state['configuration_sha256'],'task_id':'cto-review',
            'output_sha256':'d'*64,'transport':{'version':'source-review-transport-v1'},
            'questions':state['questions'][:],'resolutions':[{'index':0,'classification':'requires_ceo','quote':'','answer':''}],
            'ceo_answer_created':False,'scope_approval_created':False}
        return state

    def test_answer_binds_original_question_after_source_review_not_later_attempt(self):
        state=self.reviewed_state()
        receipt=make_answer(state,self.answer,'direct CEO reply')
        self.assertEqual(receipt['issue_id'],'issue-original')
        self.assertEqual(receipt['task_id'],'task-original')
        self.assertEqual(receipt['source_review_task_id'],'cto-review')
        result=resume(state,receipt)
        self.assertEqual(result['prior_ceo_question']['output']['task_id'],'task-original')
        self.assertEqual(result['prior_ceo_product_attempt']['output']['task_id'],'task-later')
        self.assertEqual(result['outputs'],{})

    def test_unqualified_or_stale_source_question_cannot_receive_answer(self):
        for field,value in [('stage','blocked'),('brief_sha256','wrong'),('configuration_sha256','wrong'),
                            ('transport',{}),('questions',['Unrelated?'])]:
            state=self.reviewed_state();state['source_review'][field]=value
            with self.assertRaises(ValueError):make_answer(state,self.answer,'reply')

    def test_replay_does_not_restart_completed_product_or_grant_permissions(self):
        receipt=make_answer(self.state,self.answer,'reply')
        result=resume(self.state,receipt)
        result.update(stage='plan_ready',outputs={'product':{'proposal':{'business_questions':[]}}})
        self.assertIsNone(resume(result,receipt))
        changed={**receipt,'answer':'Another answer'}
        with self.assertRaises(ValueError):resume(result,changed)

    def test_pending_requires_private_exact_receipt_and_context_reaches_compiler(self):
        import tempfile,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertFalse(pending(root,'DEMO-2',self.state))
            receipt=make_answer(self.state,self.answer,'reply')
            target=root/'planning-ceo-answers'/'DEMO-2.json';target.parent.mkdir()
            target.write_text(json.dumps(receipt));target.chmod(0o600)
            self.assertTrue(pending(root,'DEMO-2',self.state))
            target.chmod(0o644)
            with self.assertRaises(ValueError):pending(root,'DEMO-2',self.state)
        result=resume(self.state,receipt)
        self.assertIn(self.answer,context('Original brief',result))
        self.assertEqual(context('Original brief',self.state),'Original brief')

    def test_fresh_product_issue_does_not_reuse_closed_question_or_format_retry(self):
        from unittest.mock import patch
        from planning_intake import issue_for
        def cli(*args):
            if args[0]=='list':return {'issues':[]}
            if args[0]=='create':return {'id':'new','assignee_id':'product'}
            raise AssertionError(args)
        with patch('planning_intake.cli',side_effect=cli) as calls:
            issue_for('product','Accepted human context','product',run_name='DEMO-2',ceo_answer=True)
            first=calls.call_args_list[1].args
            issue_for('product','Format correction','product',run_name='DEMO-2',ceo_answer=True,retry=True)
            second=calls.call_args_list[3].args
        self.assertEqual(first[2],'DEMO-2 — product-ceoanswer1')
        self.assertEqual(second[2],'DEMO-2 — product-ceoanswer1-retry1')

    def test_supervisor_reconciles_answer_without_skipping_later_gates(self):
        import tempfile,json
        from pathlib import Path
        from brief_delivery_supervisor import supervise
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'pipeline.json'
            self.assertEqual(supervise(path,'a'*64,lambda _:1),1)
            calls=[]
            self.assertEqual(supervise(path,'a'*64,lambda step:calls.append(step) or 0,
                                       reconcile_planning=True),0)
            self.assertEqual(calls,['planning','materializing','compiling','executing'])
