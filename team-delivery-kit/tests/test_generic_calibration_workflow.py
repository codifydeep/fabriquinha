import copy
import json
import sqlite3
import unittest

from broker import generic_calibration_workflow as workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.config=dict(issue_id='issue',author_task='author-task',cto='cto',reviewer='lead',
            candidate_volume='owned-candidate',previous_volume='owned-previous',test_files=['tests/test_one.py'],
            execution_sha256='a'*64,plan_sha256='b'*64,criteria={'A01':'contract'},source_task='source')
        workflow.initialize(self.con)
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            ('issue','author-task',json.dumps(self.config),json.dumps(dict(stage='bundle_dispatch',owner='cto',
                execution_authorized=False,delivery_approval=False))))
        self.events=[];self.runs=[];self.uncertain=False
        parent=self
        class Effects:
            def verify(self,c):parent.assertEqual(c,parent.config)
            def reserve(self,c):return True
            def ready(self,c,task):return True
            def runs(self,c):return parent.runs
            def wake(self,c,note,marker,allow_create):
                parent.events.append(('wake',allow_create,marker))
                row=parent.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()
                parent.assertEqual(json.loads(row[0])['stage'],'observe_bundle_dispatch')
                if parent.uncertain:
                    parent.uncertain=False;raise TimeoutError('lost acknowledgment')
                return {'id':'wake'}
            def collect(self,c,task,wake):
                parent.events.append(('collect',task['id'],wake))
                return {'policy_sha256':'c'*64,'producer':{'task_id':task['id']},'execution_authorized':False,'delivery_approval':False}
        self.fx=Effects()

    def state(self):return json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])

    def advance(self,now=1):return workflow.advance(self.con,self.config,self.fx,now=now)

    def test_dispatch_intent_precedes_wakeup_and_lost_ack_never_replays_create(self):
        self.uncertain=True
        self.advance();self.assertEqual(self.state()['stage'],'observe_bundle_dispatch')
        self.advance(2);self.assertEqual(self.events[-1][1],False)
        self.assertEqual(self.state()['stage'],'await_bundle')
        self.assertEqual(self.events[0][2],self.events[1][2])

    def test_only_exact_terminal_native_bundle_is_collected(self):
        self.advance()
        self.runs=[dict(id='unrelated',wakeup_id='foreign',agent_id='cto',status='completed')]
        self.advance(2);self.assertEqual(self.state()['stage'],'await_bundle')
        self.runs.append(dict(id='producer',wakeup_id='wake',agent_id='cto',status='completed'))
        self.advance(3)
        self.assertEqual(self.state()['stage'],'prepare_controls')
        self.assertFalse(self.state()['execution_authorized'])
        count=len(self.events);self.advance(4);self.assertEqual(len(self.events),count)

    def test_failed_agent_and_deadline_become_owned_visible_holds(self):
        self.advance()
        self.runs=[dict(id='producer',wakeup_id='wake',agent_id='cto',status='failed')]
        self.advance(2);self.assertEqual(self.state()['stage'],'blocked')
        self.assertEqual(self.state()['owner'],'cto')
        count=len(self.events);self.advance(3);self.assertEqual(len(self.events),count)

    def test_absent_wakeup_observation_does_not_create_an_identical_replacement(self):
        self.uncertain=True;self.advance()
        self.fx.wake=lambda *a,**k:None
        self.advance(602)
        self.assertEqual(self.state()['stage'],'blocked')
        self.assertEqual(self.state()['category'],'bundle_dispatch_unobserved')

    def test_duplicate_native_runs_are_not_arbitrarily_selected(self):
        self.advance()
        self.runs=[dict(id=str(i),wakeup_id='wake',agent_id='cto',status='completed') for i in range(2)]
        self.advance(2)
        self.assertEqual(self.state()['category'],'ambiguous_bundle_runs')
        self.assertFalse(any(event[0]=='collect' for event in self.events))

    def test_persisted_configuration_cannot_change_between_restarts(self):
        config=copy.deepcopy(self.config);config['cto']='author'
        with self.assertRaises(ValueError):workflow.advance(self.con,config,self.fx,now=1)
        self.assertFalse(self.events)

    def test_missing_reserve_does_not_create_an_uncertain_dispatch_intent(self):
        self.fx.reserve=lambda c:False
        self.advance()
        self.assertEqual(self.state()['stage'],'bundle_dispatch')
        self.assertFalse(self.events)
        self.fx.reserve=lambda c:True
        self.advance(2)
        self.assertEqual(self.state()['stage'],'await_bundle')

    def test_native_completion_waits_for_the_same_lease_to_close(self):
        self.advance()
        self.runs=[dict(id='producer',wakeup_id='wake',agent_id='cto',status='completed')]
        self.fx.ready=lambda c,t:False
        self.advance(2);self.assertEqual(self.state()['stage'],'await_bundle')
        self.assertFalse(any(e[0]=='collect' for e in self.events))
        self.fx.ready=lambda c,t:True
        self.advance(3);self.assertEqual(self.state()['stage'],'prepare_controls')

    def test_oversized_context_is_not_truncated_or_dispatched(self):
        self.config['criteria']={'A01':'x'*4000}
        self.con.execute('UPDATE generic_calibration_workflows SET config=?',(json.dumps(self.config),))
        self.advance()
        self.assertEqual(self.state()['category'],'bundle_context_requires_readonly_capsule')
        self.assertFalse(self.events)

    def test_changed_source_becomes_owned_hold_before_any_wakeup(self):
        def rejected(c):raise ValueError('source changed')
        self.fx.verify=rejected
        self.advance()
        self.assertEqual(self.state()['category'],'bundle_source_binding_rejected')
        self.assertFalse(self.events)
