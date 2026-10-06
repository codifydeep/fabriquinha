"""Dispatch fixtures do not authorize or simulate a successful product delivery."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_incremental_checkpoints as checkpoint_fixtures
from broker import incremental_dispatch as runtime


class IncrementalDispatchTests(unittest.TestCase):
    def setUp(self):
        fixture=checkpoint_fixtures.IncrementalCheckpointTests();fixture.setUp()
        self.con=fixture.con;self.addCleanup(self.con.close)
        self.state=fixture.state()
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
        self.route=dict(enabled=True,author='author',minimum_calls=8,cto='cto')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('child',json.dumps(self.route)))
        self.state['execution_authorized']=True
        self.state['units']['U1']['binding']=dict(issue_id='child',materialization=dict(new_test='tests/new.py'))
        self.save()
        self.effects=SimpleNamespace(remaining_calls=Mock(return_value=71),
            implementation_available=Mock(return_value=True),ensure_unit_start=Mock(return_value={'id':'wake'}))

    def save(self):
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(self.state),))

    def dispatch(self,now=1):
        return runtime.dispatch(self.con,'source','U1',self.effects,now=now)

    def test_dispatch_is_persisted_and_not_repeated_after_restart(self):
        self.assertEqual(self.dispatch(),'dispatched')
        self.assertEqual(self.dispatch(2),'dispatched')
        self.effects.ensure_unit_start.assert_called_once()
        note=self.effects.ensure_unit_start.call_args.args[4]
        self.assertIn('unittest.TestCase',note)
        self.assertIn('not pytest imports',note)
        self.assertIn('collection/import error is not valid Red',note)

    def test_missing_binding_or_authority_never_dispatches(self):
        self.state['execution_authorized']=False;self.save()
        self.assertEqual(self.dispatch(),'paused')
        self.effects.ensure_unit_start.assert_not_called()
        del self.state['units']['U1']['binding'];self.save()
        with self.assertRaises(ValueError):self.dispatch()

    def test_budget_and_capacity_wait_remain_visible_then_resume(self):
        self.effects.remaining_calls.return_value=0
        self.assertEqual(self.dispatch(),'budget_wait')
        self.effects.ensure_unit_start.assert_not_called()
        self.effects.remaining_calls.return_value=71
        self.effects.implementation_available.return_value=False
        self.assertEqual(self.dispatch(2),'capacity_wait')
        self.effects.implementation_available.return_value=True
        self.assertEqual(self.dispatch(3),'dispatched')

    def test_unattended_work_escalates_without_success_or_infinite_retry(self):
        self.effects.implementation_available.return_value=False
        self.dispatch(1)
        self.assertEqual(self.dispatch(601),'blocked')
        self.effects.implementation_available.return_value=True
        self.assertEqual(self.dispatch(700),'blocked')
        self.effects.ensure_unit_start.assert_not_called()
        state=json.loads(self.con.execute('SELECT state FROM incremental_dispatch_intents').fetchone()[0])
        self.assertEqual(state['owner'],'cto')
        self.assertIn('required_action',state)

    def test_ambiguous_remote_effect_uses_same_marker_for_lookup(self):
        self.effects.ensure_unit_start.side_effect=[TimeoutError(),{'id':'original-remote-wake'}]
        self.assertEqual(self.dispatch(),'dispatch_intent')
        self.assertEqual(self.dispatch(2),'dispatched')
        first,second=self.effects.ensure_unit_start.call_args_list
        self.assertEqual(first.args[3],second.args[3])

    def test_two_identical_failures_require_diagnosis(self):
        self.effects.ensure_unit_start.side_effect=TimeoutError()
        self.assertEqual(self.dispatch(),'dispatch_intent')
        self.assertEqual(self.dispatch(2),'blocked')
        self.assertEqual(self.dispatch(3),'blocked')
        self.assertEqual(self.effects.ensure_unit_start.call_count,2)

    def binding_fixture(self):
        del self.state['units']['U1']['binding'];self.save()
        self.con.execute('CREATE TABLE issue_bases(issue_id,base_sha,manifest_sha256)')
        self.con.execute('CREATE TABLE native_bindings(issue_id)')
        self.con.execute('INSERT INTO issue_bases VALUES(?,?,?)',('child','a'*40,'9'*64))
        self.route.update(enabled=False,test_first=True,test_first_files=['tests/new.py'],
            techlead='lead',reviewer='cto',contract_sha256='8'*64)
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(self.route),))
        return dict(checkpoint_manifest_sha256='b'*64,base_manifest_sha256='9'*64,
            contract_sha256='8'*64,base_sha='a'*40,baseline_test_sha256={'tests/old.py':'c'*64},
            new_test='tests/new.py',suite_sha256='d'*64)

    def test_binding_retains_both_distinct_hashes_and_is_immutable(self):
        receipt=self.binding_fixture()
        # Qualification of the prior suite is independently covered by adapter tests.
        with patch.object(runtime.evidence,'_prior_suite'):
            state=runtime.bind(self.con,'source','U1','child',receipt,'7'*64)
            self.assertEqual(state['units']['U1']['base_manifest_sha256'],'b'*64)
            self.assertEqual(state['units']['U1']['materialized_base_manifest_sha256'],'9'*64)
            self.assertEqual(runtime.bind(self.con,'source','U1','child',receipt,'7'*64),state)
            with self.assertRaises(ValueError):runtime.bind(self.con,'source','U1','child',receipt,'6'*64)

    def test_active_or_already_executed_child_cannot_be_bound(self):
        receipt=self.binding_fixture()
        self.route['enabled']=True
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(self.route),))
        with self.assertRaises(ValueError):runtime.bind(self.con,'source','U1','child',receipt,'7'*64)
        self.route['enabled']=False
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(self.route),))
        self.con.execute('INSERT INTO native_bindings VALUES(?)',('child',))
        with patch.object(runtime.evidence,'_prior_suite'):
            with self.assertRaises(ValueError):runtime.bind(self.con,'source','U1','child',receipt,'7'*64)
