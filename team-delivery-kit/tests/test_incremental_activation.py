import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_incremental_dispatch as fixtures
from broker import incremental_dispatch as dispatch
from broker import incremental_provisioning as provision


class ActivationTests(unittest.TestCase):
    def next_fixture(self):
        from broker import incremental_checkpoints as ledger
        provision.activate_first(self.b,'source')
        state=json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])
        state['units']['U1']['stage']='checkpointed'
        binding=state['units']['U1']['binding']
        state['units']['U2'].update(stage='awaiting_red',binding={**binding,'issue_id':'child2'})
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        route=json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0]);route.update(issue_id='child2',enabled=False)
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('child2',json.dumps(route)))
        self.con.execute('INSERT INTO incremental_unit_owners VALUES(?,?,?,?)',('child2','source','U2',1))
        self.con.execute('CREATE TABLE incremental_runtime_incidents(source_task)')

    def test_dependent_activation_exact_scope_and_repeat(self):
        self.next_fixture();receipt=provision.activate_next(self.b,'source','U2')
        self.assertEqual(provision.activate_next(self.b,'source','U2'),receipt)
        state=json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])
        self.assertEqual(state['execution_units'],['U1','U2']);self.assertFalse(receipt['delivery_approval'])
        with self.assertRaises(ValueError):provision.activate_next(self.b,'source','U3')

    def test_dependent_activation_rolls_back_and_rejects_drift(self):
        self.next_fixture()
        self.b.issue_base.return_value={'manifest_sha256':'0'*64}
        with self.assertRaises(ValueError):provision.activate_next(self.b,'source','U2')
        self.b.issue_base.return_value={'manifest_sha256':'9'*64}
        self.con.execute("CREATE TRIGGER next_activation_failure BEFORE UPDATE ON incremental_checkpoints BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):provision.activate_next(self.b,'source','U2')
        route=json.loads(self.con.execute("SELECT config FROM delivery_routes WHERE issue_id='child2'").fetchone()[0]);self.assertFalse(route['enabled'])

    def test_dependent_repair_requires_registered_sponsorship_before_unpausing(self):
        self.next_fixture()
        state=json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])
        state['execution_authorized']=False
        state['units']['U2']['test_repair']=dict(parent_issue='old-child2',decision_task='cto-task')
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):provision.activate_next(self.b,'source','U2')
        self.con.execute('CREATE TABLE test_revision_trials(issue_id,config)')
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('child2',json.dumps(dict(parent_issue='wrong',cto_decision='cto-task'))))
        with self.assertRaises(ValueError):provision.activate_next(self.b,'source','U2')
        self.con.execute('UPDATE test_revision_trials SET config=?',(json.dumps(dict(parent_issue='old-child2',cto_decision='cto-task')),))
        provision.activate_next(self.b,'source','U2')
        self.assertTrue(json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])['execution_authorized'])

    def setUp(self):
        fixture=fixtures.IncrementalDispatchTests();fixture.setUp()
        self.con=fixture.con;self.addCleanup(self.con.close)
        receipt=fixture.binding_fixture()
        fixture.state['execution_authorized']=False;fixture.save()
        with patch.object(dispatch.evidence,'_prior_suite'):
            dispatch.bind(self.con,'source','U1','child',receipt,'7'*64)
        self.con.execute('CREATE TABLE leases(status)')
        class Context:
            def __enter__(_):return self.con
            def __exit__(_,kind,value,tb):self.con.commit() if kind is None else None
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=lambda:Context(),issue_base=Mock(return_value={'manifest_sha256':'9'*64}))
        self.proof=patch.object(dispatch.evidence,'_prior_suite');self.proof.start();self.addCleanup(self.proof.stop)

    def test_first_trial_authorizes_only_u1_never_delivery(self):
        receipt=provision.activate_first(self.b,'source')
        state=json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])
        self.assertEqual(state['execution_units'],['U1'])
        self.assertTrue(state['execution_authorized']);self.assertFalse(state['delivery_approval'])
        self.assertEqual(provision.activate_first(self.b,'source'),receipt)

    def test_partial_activation_rolls_back_route_and_ledger_together(self):
        self.con.execute("CREATE TRIGGER activation_failure BEFORE UPDATE ON incremental_checkpoints BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):provision.activate_first(self.b,'source')
        self.assertFalse(json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])
        self.assertFalse(json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])['execution_authorized'])

    def test_live_worker_or_open_incident_prevents_activation(self):
        self.con.execute("INSERT INTO leases VALUES('running')")
        with self.assertRaises(ValueError):provision.activate_first(self.b,'source')
        self.con.execute('DELETE FROM leases')
        self.con.execute('CREATE TABLE incremental_runtime_incidents(source_task)')
        self.con.execute("INSERT INTO incremental_runtime_incidents VALUES('source')")
        with self.assertRaises(ValueError):provision.activate_first(self.b,'source')

    def test_changed_base_cannot_receive_execution_authority(self):
        self.b.issue_base.return_value={'manifest_sha256':'0'*64}
        with self.assertRaises(ValueError):provision.activate_first(self.b,'source')

    def test_repair_must_be_registered_with_exact_parent_and_cto(self):
        state=json.loads(self.con.execute('SELECT state FROM incremental_checkpoints').fetchone()[0])
        state['units']['U1']['test_repair']=dict(parent_issue='old-child',decision_task='cto-task')
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):provision.activate_first(self.b,'source')
        self.con.execute('CREATE TABLE test_revision_trials(issue_id,config)')
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?)',
            ('child',json.dumps(dict(parent_issue='wrong',cto_decision='cto-task'))))
        with self.assertRaises(ValueError):provision.activate_first(self.b,'source')
        self.con.execute('UPDATE test_revision_trials SET config=?',
            (json.dumps(dict(parent_issue='old-child',cto_decision='cto-task')),))
        self.assertEqual(provision.activate_first(self.b,'source')['mode'],'tests_only')
