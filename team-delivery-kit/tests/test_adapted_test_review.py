import unittest
from broker.adapted_test_review import validate_verdict, instruction, preservation_facts, replan_instruction, validate_replan, author_instruction, validate_author_sponsorship
import hashlib
import json
import tempfile
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import Mock, patch
from broker import adapted_test_review as review, handoffs, handoff_runtime, native


class AdaptedReviewTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(revision_id='revision', issue_id='issue', author='author',
            reviewer='reviewer', manifest_sha256='a'*64,
            required_paths=['/evidence/candidate/tests/test_new.py', '/evidence/previous/tests/test_new.py'])
        self.task = dict(id='task', agent_id='reviewer', issue_id='issue', status='completed', wakeup_id='wake')
        self.state = dict(wakeup_id='wake')
        self.reads = {p:dict(lines=10,total_lines=10) for p in self.config['required_paths']}
        self.decision = dict(action='approve_test_revision', reason='Preserved tests.', optional_files=[], manifest_sha256='a'*64)

    def test_exact_independent_complete_verdict_accepted(self):
        result = validate_verdict(self.config,self.state,self.task,self.decision,self.reads)
        self.assertEqual(result['status'],'approved_for_red_capture')
        self.assertFalse(result['delivery_approval'])
        self.assertFalse(result['implementation_authorized'])

    def test_wrong_snapshot_author_or_wakeup_rejected(self):
        for task, decision in (({**self.task,'agent_id':'author'},self.decision),
                               ({**self.task,'wakeup_id':'other'},self.decision),
                               (self.task,{**self.decision,'manifest_sha256':'b'*64})):
            with self.assertRaises(ValueError):
                validate_verdict(self.config,self.state,task,decision,self.reads)

    def test_partial_or_missing_reads_rejected(self):
        for reads in ({}, {p:dict(lines=1,total_lines=10) for p in self.reads}):
            with self.assertRaises(ValueError):
                validate_verdict(self.config,self.state,self.task,self.decision,reads)

    def test_rejection_is_not_approval(self):
        result=validate_verdict(self.config,self.state,self.task,{**self.decision,'action':'reject_test_revision'},self.reads)
        self.assertEqual(result['status'],'changes_requested')
        self.assertFalse(result['implementation_authorized'])

    def test_instruction_requires_reads_and_exact_typed_verdict(self):
        text=instruction(self.config)
        self.assertIn('DELIVERY_TYPED_REVIEW_V1:'+'a'*64,text)
        self.assertIn('DELIVERY_REVIEW_READ_PATH:'+self.config['required_paths'][0],text)
        self.assertIn('not a Red receipt',text)

    def test_preservation_compares_bodies_not_class_or_traversal_order(self):
        original=b'def test_one():\n    assert True\ndef helper():\n    assert 2 == 2\n'
        candidate=b'def helper():\n    assert 2 == 2\nclass Wrapped:\n    def test_one(self):\n        assert True\n'
        facts=preservation_facts(original,candidate,hashlib.sha256(original).hexdigest(),hashlib.sha256(candidate).hexdigest())
        self.assertTrue(facts['test_bodies_preserved'])
        self.assertTrue(facts['assertions_preserved'])
        self.assertEqual(facts['test_constant_true_assertions'],1)
        self.assertFalse(facts['semantic_approval'])
        with self.assertRaises(ValueError):
            preservation_facts(original,candidate,'f'*64,hashlib.sha256(candidate).hexdigest())

    def test_cto_replan_requires_exact_execution_and_complete_reads(self):
        config={**self.config,'cto':'cto'}
        task={**self.task,'agent_id':'cto'}
        decision=dict(action='request_test_revision',reason='Correct NEW coverage only.',optional_files=[])
        self.assertEqual(validate_replan(config,self.state,task,decision,self.reads)['status'],'test_revision_requested')
        for bad in ({**decision,'action':'retry_author'},{**decision,'optional_files':['contract.json']}):
            with self.assertRaises(ValueError):validate_replan(config,self.state,task,bad,self.reads)
        with self.assertRaises(ValueError):validate_replan(config,self.state,task,decision,{})

    def test_cto_instruction_preserves_rejection_and_does_not_approve(self):
        config={**self.config,'preservation_facts':{'assertions_preserved':True}}
        state={'decision':{**self.decision,'action':'reject_test_revision'}}
        text=replan_instruction(config,state)
        self.assertIn('DELIVERY_STRUCTURED_DECISION_V1:technical',text)
        self.assertIn('not implementation',text)
        self.assertIn('Do not treat a disputed claim as a proven fact',text)

    def test_cto_instruction_activates_actual_typed_submission(self):
        from decision_schema import apply as schema
        from typed_decision_contract import apply as typed, NAME
        config={**self.config,'preservation_facts':{'assertions_preserved':True}}
        state={'decision':{**self.decision,'action':'reject_test_revision'}}
        body=dict(messages=[{'role':'user','content':replan_instruction(config,state)}],max_tokens=2048)
        for index,path in enumerate(config['required_paths']):
            call=str(index)
            body['messages'].extend([
                {'role':'assistant','tool_calls':[{'id':call,'function':{'name':'read_file','arguments':json.dumps({'path':path})}}]},
                {'role':'tool','tool_call_id':call,'content':json.dumps({'content':'1|assert value\n','total_lines':1})}])
        actual=typed(schema(body))
        self.assertEqual(actual.get('tool_choice'),{'type':'function','function':{'name':NAME}})
        self.assertNotIn('response_format',actual)
        self.assertEqual(actual['tools'][0]['function']['parameters']['properties']['optional_files']['maxItems'],0)

    def test_author_sponsorship_keeps_real_request_and_snapshot_identity(self):
        config={**self.config,'cto':'cto','source_task':'original'}
        route=dict(enabled=True,test_first=True,author='author',techlead='reviewer',cto='cto',test_first_files=['tests/test_new.py'])
        decision=dict(action='request_test_revision',reason='Restore meaningful NEW coverage.',optional_files=[])
        state={'status':'changes_requested','replan':dict(status='test_revision_requested',task_id='task',wakeup_id='wake',decision=decision,manifest_sha256='a'*64)}
        task={**self.task,'agent_id':'cto'}
        validate_author_sponsorship(config,state,route,task,decision,self.reads,'original',False)
        for latest,red in (('other',False),('original',True)):
            with self.assertRaises(ValueError):validate_author_sponsorship(config,state,route,task,decision,self.reads,latest,red)
        with self.assertRaises(ValueError):validate_author_sponsorship(config,state,{**route,'author':'other'},task,decision,self.reads,'original',False)
        state['author_revision']={'bootstrap_recovery':dict(operation='qualified_zero_call_bootstrap_recovery_v1',sponsor_task='task',manifest_sha256='a'*64,zero_tools=True,zero_model_calls=True,fixed_config_probe='passed',failed_task='bootstrap-failed')}
        validate_author_sponsorship(config,state,route,task,decision,self.reads,'bootstrap-failed',False)
        with self.assertRaises(ValueError):validate_author_sponsorship(config,state,route,task,decision,self.reads,'unrelated',False)
        state['author_revision']['bootstrap_recovery']['zero_tools']=False
        with self.assertRaises(ValueError):validate_author_sponsorship(config,state,route,task,decision,self.reads,'bootstrap-failed',False)
        del state['author_revision']
        note=author_instruction(config,state,route)
        self.assertIn('TESTS ONLY',note)
        self.assertIn('unittest.TestCase',note)
        self.assertIn('Restore meaningful NEW coverage.',note)
        self.assertNotIn('DELIVERY_STRUCTURED_DECISION_V1',note)

    def exercise_author_dispatch(self, restart=False):
        config={**self.config,'cto':'cto','source_task':'original'}
        route=dict(enabled=True,test_first=True,author='author',techlead='reviewer',cto='cto',test_first_files=['tests/test_new.py'],minimum_calls=8)
        decision=dict(action='request_test_revision',reason='Add actual NEW coverage.',optional_files=[])
        state={'status':'changes_requested','replan':dict(status='test_revision_requested',task_id='task',wakeup_id='wake',decision=decision,manifest_sha256='a'*64)}
        with tempfile.TemporaryDirectory() as tmp:
            class Broker:
                STATE=Path(tmp)
                @contextmanager
                def db(self):
                    con=sqlite3.connect(Path(tmp)/'state.sqlite');con.row_factory=sqlite3.Row
                    try:
                        with con:yield con
                    finally:con.close()
            b=Broker();(b.STATE/'native.json').write_text('{}')
            with b.db() as con:
                handoffs.initialize(con);review.initialize(con)
                con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
                con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(route)))
                con.execute('INSERT INTO adapted_test_reviews VALUES(?,?,?)',('revision',json.dumps(config),json.dumps(state)))
                handoffs.save(con,'original','issue','test_first_blocked','cto',{},1)
            fx=Mock();fx.implementation_available.return_value=True;fx.remaining_calls.return_value=25
            fx.decision.return_value=decision;fx.read_evidence.return_value=self.reads
            fx.ensure_wakeup.return_value={'id':'author-wake'}
            if restart:
                state['author_revision']=dict(status='pending',marker='stable',dispatch_intent_at=1)
                fx.implementation_available.return_value=False
            task={**self.task,'agent_id':'cto'}
            with patch.object(handoff_runtime,'Effects',return_value=fx),patch.object(handoff_runtime,'safe_publish'),patch.object(native,'task_record',return_value=task),patch.object(native,'issue_task_runs',return_value=[dict(id='original',agent_id='author',status='failed',created_at='1')]):
                review._advance_author(b,config,state)
                self.assertEqual(state['author_revision']['status'],'awaiting_author')
                self.assertEqual(state['author_revision']['wakeup_id'],'author-wake')
                fx.ensure_wakeup.assert_called_once()
                self.assertEqual(fx.ensure_wakeup.call_args.kwargs['allow_create'],not restart)
                if restart:fx.implementation_available.assert_not_called()
                else:
                    with b.db() as con:
                        saved=handoffs.load(con,'original')
                    self.assertEqual(saved['stage'],'test_first_cto_correction_wait')
                    self.assertEqual(saved['owner'],'author')
                    self.assertIn('adapted_author_revision',json.loads(saved['data']))

    def test_dispatch_persists_tests_only_wait_before_real_author_wakeup(self):
        self.exercise_author_dispatch()

    def test_restart_reconciles_existing_wakeup_even_if_author_is_busy(self):
        self.exercise_author_dispatch(restart=True)

    def test_only_exact_consumed_surgical_recipient_can_retire_old_policy(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        self.addCleanup(con.close);handoffs.initialize(con)
        con.execute('CREATE TABLE surgical_test_recoveries(issue_id TEXT,config TEXT)')
        con.execute('INSERT INTO surgical_test_recoveries VALUES(?,?)',('issue',json.dumps({'source_task':'old-policy-source'})))
        handoffs.save(con,'old-policy-source','issue','test_first_surgical_recovery_wait','author',{'surgical_wakeup':'old-wake'},1)
        config={**self.config,'source_task':'original','cto':'cto'}
        state={'replan':dict(status='test_revision_requested',task_id='cto-task')}
        original=dict(id='original',agent_id='author',issue_id='issue',status='failed',wakeup_id='old-wake')
        with self.assertRaises(ValueError):review.retire_consumed_surgical_policy(con,config,state,{**original,'wakeup_id':'other'})
        review.retire_consumed_surgical_policy(con,config,state,original)
        self.assertEqual(handoffs.load(con,'old-policy-source')['stage'],'test_first_surgical_recovery_superseded')
        self.assertEqual(con.execute('SELECT count(*) FROM surgical_test_recoveries').fetchone()[0],1)
        review.retire_consumed_surgical_policy(con,config,state,original)

    def test_existing_test_phase_markers_require_actual_registered_author(self):
        config={**self.config,'author_revision_enabled':True}
        state=dict(replan={'status':'test_revision_requested'},author_revision={'status':'awaiting_author','wakeup_id':'wake','marker':'marker'})
        task=dict(agent_id='author',issue_id='issue',wakeup_id='wake',handoff_note='DELIVERY_HANDOFF marker')
        text=review.author_phase_markers(config,state,task,'tests/test_new.py')
        self.assertIn('DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py',text)
        self.assertIn('DELIVERY_DETERMINISTIC_READ_V1',text)
        for wrong in ({**task,'agent_id':'reviewer'},{**task,'wakeup_id':'other'}):
            self.assertEqual(review.author_phase_markers(config,state,wrong,'tests/test_new.py'),'')
