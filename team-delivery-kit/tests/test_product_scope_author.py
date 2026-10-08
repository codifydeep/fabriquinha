import json
import unittest
import uuid
from unittest.mock import patch
import test_product_scope_worker as fixtures
from broker import product_scope_author as author, product_scope_ledger as ledger, native


class ProductScopeAuthorTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeWorkerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b,self.fx,self.key=self.f.b,self.f.fx,self.f.key
        with self.b.db() as con:
            con.execute('DELETE FROM product_scope_task_bases')
            state=ledger.load(con,self.key)
            self.state=ledger.save_transition(con,state,dict(state,dispatch={k:v for k,v in state['dispatch'].items() if k!='author'}))
        self.task=self.f.f.task
        self.task['handoff_note']=author.exact_note(self.state)
        self.fx.author_wake.return_value=dict(id='author-wake',last_task_id=None)

    def test_unknown_ack_preserves_one_intent_and_reconciles_same_marker(self):
        self.fx.author_wake.side_effect=[TimeoutError('ack'),dict(id='author-wake',last_task_id=None)]
        with self.assertRaises(TimeoutError):author.tick(self.b,self.key,self.fx,now=1)
        state=author.tick(self.b,self.key,self.fx,now=2)
        self.assertEqual(state['dispatch']['author']['stage'],'observing')
        self.assertEqual(self.fx.author_wake.call_args_list[0].args[1:],self.fx.author_wake.call_args_list[1].args[1:])
        self.assertTrue(state['author_blocked'])
        self.assertFalse(state['delivery_approval'])

    def test_admission_can_reconcile_wakeup_before_tick_receives_its_ack(self):
        self.fx.author_wake.side_effect=TimeoutError('ack')
        with self.assertRaises(TimeoutError):author.tick(self.b,self.key,self.fx,now=1)
        self.fx.author_wake.side_effect=None
        self.fx.author_wake.return_value=dict(id='author-wake',last_task_id='new-author')
        selected=author.admit(self.b,self.task,self.fx)
        self.assertEqual(selected['task_id'],'new-author')
        self.assertFalse(selected['write_grant_issued'])
        calls=self.fx.author_wake.call_count
        state=author.tick(self.b,self.key,self.fx)
        self.assertEqual(state['dispatch']['author']['stage'],'admitted')
        self.assertEqual(self.fx.author_wake.call_count,calls)
        self.assertEqual(author.prompt(self.b,self.task),self.task['handoff_note'])
        self.assertEqual(author.admit(self.b,self.task,self.fx),selected)

    def test_unknown_or_altered_notes_cannot_admit_or_replace_prompt(self):
        author.tick(self.b,self.key,self.fx,now=1)
        self.fx.author_wake.return_value=dict(id='author-wake',last_task_id='new-author')
        with self.assertRaises(ValueError):author.admit(self.b,dict(self.task,handoff_note=self.task['handoff_note']+' change'),self.fx)
        author.admit(self.b,self.task,self.fx)
        for mutation in ({'agent_id':'cto'},{'wakeup_id':'other'},{'handoff_note':'unregistered'}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):author.prompt(self.b,dict(self.task,**mutation))

    def test_terminal_failure_and_missing_wakeup_block_without_repeated_dispatch(self):
        state=author.tick(self.b,self.key,self.fx,now=1)
        self.task['status']='failed'
        self.fx.author_wake.return_value=dict(id='author-wake',last_task_id='new-author')
        held=author.tick(self.b,self.key,self.fx,now=2)
        self.assertEqual(held['dispatch']['author']['stage'],'blocked')
        calls=self.fx.author_wake.call_count
        self.assertEqual(author.tick(self.b,self.key,self.fx,now=900),held)
        self.assertEqual(self.fx.author_wake.call_count,calls)
        with self.assertRaises(ValueError):author.admit(self.b,self.task,self.fx)

    def test_missing_historical_review_blocks_admission_before_any_tool_grant(self):
        author.tick(self.b,self.key,self.fx,now=1)
        self.fx.author_wake.return_value=dict(id='author-wake',last_task_id='new-author')
        with self.b.db() as con:con.execute('DELETE FROM test_revision_trials')
        with self.assertRaises(ValueError):author.admit(self.b,self.task,self.fx)
        with self.b.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='grants'").fetchone())
            state=ledger.load(con,self.key)
            self.assertEqual(state['dispatch']['author']['stage'],'blocked')
        with self.assertRaises(ValueError):author.admit(self.b,self.task,self.fx)

    def test_scope_author_uses_new_task_workspace_not_issue_workspace(self):
        task,issue,actor,workspace=(str(uuid.uuid4()) for _ in range(4))
        settings=dict(agents={actor:'implementation'},workspace_id=workspace)
        record=dict(id=task,issue_id=issue,status='running',wakeup_id='wake',
                    handoff_note='DELIVERY_SCOPE_AUTHOR_START '+'a'*64+'\nSource: '+issue)
        with patch.object(native,'task_record',return_value=record):
            scoped=native.task_binding(settings,task,actor)
            self.assertTrue(scoped['scope'].endswith(':'+task))
        record['handoff_note']='Legacy correction'
        with patch.object(native,'task_record',return_value=record):
            self.assertTrue(native.task_binding(settings,task,actor)['scope'].endswith(':'+issue))
