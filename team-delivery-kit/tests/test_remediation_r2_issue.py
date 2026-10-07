import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_remediation_red_reference as fixtures
from broker import remediation_r2_issue as sequencer


class RemediationR2IssueTests(unittest.TestCase):
    ITEM_ID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    def setUp(self):
        fixture=fixtures.RemediationRedReferenceTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.f=fixture;self.b=fixture.b
        self.value=fixture.value
        self.value['steps'][1]['objective']='Deliver complete product behavior against frozen tests.'
        from broker.technical_remediation_plan import digest
        self.f.state['contract_sha256']=digest(self.value)
        self.f.state['r1_gate']['execution_contract_sha256']=digest(self.value)
        fixture.f.f.save(value=self.value,state=self.f.state)
        self.calls=[]
        self.parent=dict(id='root',project_id='project',status='in_progress')
        def ensure(desired,*,allow_create):
            self.calls.append(allow_create)
            return dict(id=self.ITEM_ID,identifier='EVAL-R2')
        self.fx=SimpleNamespace(issues=SimpleNamespace(request=lambda path:self.parent,ensure=ensure),
                                native=SimpleNamespace())

    def invoke(self,now=100):
        with patch.object(sequencer.planning,'Effects',return_value=self.fx),patch.object(sequencer.review,'verify'):
            return sequencer.provision(self.b,'source',now=now)

    def test_new_card_preserves_full_scope_parent_and_no_assignment_or_execution(self):
        spec=sequencer.issue_spec(self.value,self.f.state,self.parent)
        self.assertIn('A01: full criterion',spec['description'])
        self.assertIn('R2',spec['description'])
        self.assertIn('origin=r1',spec['description'])
        self.assertEqual(spec['parent_issue_id'],'root')
        self.assertNotIn('assignee_id',spec)
        self.assertEqual(spec['status'],'todo')
        receipt=self.invoke()
        self.assertEqual(receipt['stage'],'issue_created')
        self.assertFalse(receipt['execution_authorized'])
        self.assertEqual(self.invoke(),receipt)
        self.assertEqual(self.calls,[True])
        with self.b.db() as c:
            state=json.loads(c.execute('SELECT state FROM remediation_executions').fetchone()[0])
            self.assertEqual(state['steps']['R2']['issue_id'],self.ITEM_ID)
            self.assertEqual(state['steps']['R1']['stage'],'approved')
            self.assertFalse(state['r1_gate']['release_homologated'])

    def test_uncertain_post_is_observed_and_never_repeated(self):
        def ensure(desired,*,allow_create):
            self.calls.append(allow_create)
            if allow_create:raise TimeoutError()
            return None if len(self.calls)==2 else dict(id=self.ITEM_ID,identifier='EVAL-R2')
        self.fx.issues.ensure=ensure
        self.assertEqual(self.invoke()['stage'],'issue_observe')
        self.assertEqual(self.invoke(now=120)['stage'],'issue_observe')
        self.assertEqual(self.invoke(now=140)['stage'],'issue_created')
        self.assertEqual(self.calls,[True,False,False])

    def test_cancelled_parent_missing_approval_or_active_lease_prevents_creation(self):
        self.parent['status']='cancelled'
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[])
        self.parent['status']='in_progress'
        with self.b.db() as c:
            c.execute('INSERT INTO leases VALUES (?,?)',('active','running'))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('new-author-task','r1','scope','author','active'))
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[])

    def test_read_only_observation_deadline_produces_visible_hold_not_another_post(self):
        def ensure(desired,*,allow_create):
            self.calls.append(allow_create)
            return None
        self.fx.issues.ensure=ensure
        self.assertEqual(self.invoke()['stage'],'issue_observe')
        self.assertEqual(self.invoke(now=701)['stage'],'issue_observe')
        receipt=self.invoke(now=1901)
        self.assertEqual(receipt['stage'],'blocked')
        self.assertEqual(receipt['owner'],'lead')
        self.assertEqual(self.invoke(now=2000),receipt)
        self.assertEqual(self.calls,[True,False,False])
        with self.b.db() as c:
            state=json.loads(c.execute('SELECT state FROM remediation_executions').fetchone()[0])
            self.assertEqual(state['r2_issue_hold']['category'],'dependent_issue_observation_deadline')
            self.assertEqual(c.execute('SELECT stage FROM delivery_handoffs WHERE issue_id=?',('r1',)).fetchone()[0],
                             'remediation_r2_blocked')

    def test_missing_real_r1_gate_cannot_start_creation(self):
        bad=copy.deepcopy(self.f.state);bad.pop('r1_gate')
        self.f.f.f.save(state=bad)
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[])

    def test_create_intent_survives_restart_without_permission_to_post_again(self):
        def ensure(desired,*,allow_create):
            self.calls.append(allow_create)
            if allow_create:raise KeyboardInterrupt()
            return dict(id=self.ITEM_ID,identifier='EVAL-R2')
        self.fx.issues.ensure=ensure
        with self.assertRaises(KeyboardInterrupt):self.invoke()
        self.assertEqual(self.invoke(now=150)['stage'],'issue_created')
        self.assertEqual(self.calls,[True,False])

    def test_watchdog_preserves_pre_intent_failure_with_owner_and_no_identical_retry(self):
        self.parent['status']='cancelled'
        with patch.object(sequencer.planning,'Effects',return_value=self.fx),patch.object(sequencer.review,'verify'):
            sequencer.tick(self.b)
            sequencer.tick(self.b)
        with self.b.db() as c:
            state=json.loads(c.execute('SELECT state FROM remediation_executions').fetchone()[0])
            self.assertEqual(state['r2_issue_hold']['owner'],'lead')
            self.assertFalse(state['r2_issue_hold']['release_homologated'])
            handoff=c.execute('SELECT stage,owner FROM delivery_handoffs WHERE issue_id=?',('r1',)).fetchone()
            self.assertEqual(tuple(handoff),('remediation_r2_blocked','lead'))
        self.assertEqual(self.calls,[])

    def test_watchdog_waits_for_closing_lease_without_false_technical_hold(self):
        with self.b.db() as c:
            c.execute('INSERT INTO leases VALUES (?,?)',('review-closing','closing'))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('review','r1','scope','lead','review-closing'))
        with patch.object(sequencer.planning,'Effects',return_value=self.fx),patch.object(sequencer.review,'verify'):
            sequencer.tick(self.b)
        with self.b.db() as c:
            state=json.loads(c.execute('SELECT state FROM remediation_executions').fetchone()[0])
            self.assertNotIn('r2_issue_hold',state)
            self.assertEqual(c.execute('SELECT count(*) FROM remediation_r2_issues').fetchone()[0],0)
        self.assertEqual(self.calls,[])

    def test_unrelated_active_worker_cannot_starve_unassigned_dependent_card_creation(self):
        with self.b.db() as c:
            c.execute('INSERT INTO leases VALUES (?,?)',('unrelated','running'))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('other-task','other-issue','scope','other-agent','unrelated'))
        self.assertEqual(self.invoke()['stage'],'issue_created')
        self.assertEqual(self.calls,[True])


if __name__=='__main__':unittest.main()
