import json
import unittest
from unittest.mock import patch
import test_product_scope_registration as fixtures
from broker import product_scope_registration as registration
from broker import product_scope_task_binding as binding
from broker import product_scope_ledger as ledger


class ProductScopeTaskBindingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeRegistrationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b,self.fx,self.key=self.f.b,self.f.fx,self.f.key
        with patch.object(registration.validation_job,'run',return_value=self.f.result):
            state=registration.tick(self.b,self.key,self.fx)
        with self.b.db() as con:
            self.state=ledger.save_transition(con,state,dict(state,dispatch=dict(state['dispatch'],
                author=dict(task_id='new-author',wakeup_id='author-wake'))))
        self.task=dict(id='new-author',agent_id=self.state['context']['author'],
                       issue_id=self.state['context']['issue_id'],status='running',wakeup_id='author-wake')
        prior=self.fx.task.side_effect
        self.fx.task.side_effect=lambda task,actor:self.task if task=='new-author' else prior(task,actor)

    def test_explicit_task_binding_is_immutable_and_does_not_grant_edits(self):
        result=binding.bind(self.b,self.key,'new-author',self.fx)
        self.assertFalse(result['write_grant_issued']);self.assertFalse(result['delivery_approval'])
        self.assertEqual(binding.bind(self.b,self.key,'new-author',self.fx),result)
        self.assertEqual(binding.lookup(self.b,'issue','new-author'),result)
        self.assertIsNone(binding.lookup(self.b,'issue','source'))
        self.assertEqual(self.b.issue_base('issue'),self.f.f.base)
        with self.b.db() as con:
            self.assertTrue(ledger.load(con,self.key)['author_blocked'])
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='task_contracts'").fetchone())

    def test_no_implicit_latest_base_for_other_tasks_or_issues(self):
        binding.bind(self.b,self.key,'new-author',self.fx)
        self.assertIsNone(binding.lookup(self.b,'issue','later-task'))
        with self.assertRaises(ValueError):binding.lookup(self.b,'other-issue','new-author')

    def test_wrong_native_task_identity_cannot_bind(self):
        for mutation in ({'agent_id':'cto'},{'issue_id':'other'},{'status':'completed'},
                         {'wakeup_id':'old-wake'},{'id':'source'}):
            original=self.task.copy();self.task.update(mutation)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                binding.bind(self.b,self.key,'new-author',self.fx)
            self.task=original

    def test_already_granted_or_legacy_bound_tasks_cannot_change_base(self):
        for table in ('grants','task_contracts'):
            with self.b.db() as con:
                con.execute('CREATE TABLE '+table+'(task_id TEXT)')
                con.execute('INSERT INTO '+table+' VALUES (?)',('new-author',))
            with self.subTest(table=table),self.assertRaises(ValueError):
                binding.bind(self.b,self.key,'new-author',self.fx)
            with self.b.db() as con:con.execute('DROP TABLE '+table)

    def test_registry_or_volume_drift_is_not_silently_accepted(self):
        binding.bind(self.b,self.key,'new-author',self.fx)
        self.b.docker.return_value=None;self.b.docker.side_effect=None
        with self.assertRaises(ValueError):binding.lookup(self.b,'issue','new-author')

    def test_dispatch_intent_is_required_and_one_plan_cannot_move_to_another_task(self):
        binding.bind(self.b,self.key,'new-author',self.fx)
        with self.b.db() as con:
            state=ledger.load(con,self.key)
            ledger.save_transition(con,state,dict(state,dispatch=dict(state['dispatch'],
                author=dict(task_id='another',wakeup_id='author-wake'))))
        with self.assertRaises(ValueError):binding.bind(self.b,self.key,'new-author',self.fx)
        prior=self.fx.task.side_effect
        self.fx.task.side_effect=lambda task,actor:dict(self.task,id='another') if task=='another' else prior(task,actor)
        with self.assertRaises(ValueError):binding.bind(self.b,self.key,'another',self.fx)

    def test_approval_is_reauthenticated_before_binding(self):
        self.fx.verify_binding.side_effect=ValueError('stale sponsor')
        with self.assertRaises(ValueError):binding.bind(self.b,self.key,'new-author',self.fx)
        self.assertIsNone(binding.lookup(self.b,'issue','new-author'))
