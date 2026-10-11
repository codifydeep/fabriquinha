import copy
import json
import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from broker import generic_calibration_approvals as approvals
from broker import generic_calibration_gate as gate
from generic_harness_calibration import digest
import test_generic_calibration_gate as samples


class ApprovalWorkflowTests(unittest.TestCase):
    def setUp(self):
        sample=samples.GenericCalibrationGateTests();sample.setUp();self.addCleanup(sample.doCleanups)
        self.policy=sample.policy;self.context=sample.context;self.reads=sample.reads
        self.c=dict(issue_id='issue',author_task='author-task',cto='cto',reviewer='lead')
        self.source=dict(policy=self.policy,context={k:v for k,v in self.context.items()
            if k not in ('proposal_wakeup','review_wakeup')},previous={'volume':'owned-previous'})
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE generic_calibration_workflows(issue_id TEXT,author_task TEXT,config TEXT,state TEXT)')
        self.initial=dict(stage='controls_ready',bundle_sha256='b'*64,policy_sha256=digest(self.policy),
            producer_task='bundle-task',execution_authorized=False,delivery_approval=False)
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            ('issue','author-task',json.dumps(self.c),json.dumps(self.initial)))
        self.tasks=[];self.effects=[];self.closed=True;self.intakes=[];parent=self
        class Effects:
            def verify(self,c):parent.assertEqual(c,parent.c)
            def approval_source(self,c,s):return copy.deepcopy(parent.source)
            def reserve(self,c):return True
            def wake_policy(self,c,actor,note,marker,allow_create):
                phase='attestation' if actor=='cto' else 'review'
                parent.assertEqual(parent.state()['stage'],'policy_'+phase+'_observe')
                parent.effects.append((phase,allow_create,marker,note))
                return {'id':phase+'-wake'}
            def runs(self,c):return parent.tasks
            def ready(self,c,t):return parent.closed
            def policy_task(self,c,tid,actor):
                return next(t for t in parent.tasks if t['id']==tid and t['agent_id']==actor)
            def policy_reads(self,t):return copy.deepcopy(parent.reads)
            def persist_intake(self,c,s,intake):parent.intakes.append(copy.deepcopy(intake));return intake
        self.fx=Effects()

    def state(self):return json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
    def advance(self,now=1):return approvals.advance(self.con,self.c,self.fx,now=now)
    def complete(self,phase):
        actor='cto' if phase=='attestation' else 'lead'
        self.tasks.append(dict(id=phase+'-task',agent_id=actor,issue_id='issue',wakeup_id=phase+'-wake',
            status='completed',result={'output':json.dumps(dict(action='propose_calibration' if actor=='cto'
                else 'approve_calibration',policy_sha256=digest(self.policy),
                controls_manifest_sha256=self.policy['controls_manifest_sha256'],
                execution_authorized=False,delivery_approval=False))}))

    def test_distinct_native_approvals_produce_intake_not_delivery_or_test_permission(self):
        self.advance();self.complete('attestation');self.advance(2)
        self.assertEqual(self.state()['stage'],'policy_review_dispatch')
        self.advance(3);self.complete('review');self.advance(4)
        self.assertEqual(self.state()['stage'],'inputs_ready')
        self.assertEqual(len(self.intakes),1)
        intake=self.intakes[0]
        self.assertEqual(intake['proposal_task'],'attestation-task')
        self.assertNotEqual(intake['proposal_task'],'bundle-task')
        self.assertEqual(intake['review_task'],'review-task')
        self.assertFalse(self.state()['execution_authorized'])
        self.assertFalse(self.state()['delivery_approval'])
        self.advance(5);self.assertEqual(len(self.intakes),1)

    def test_lost_dispatch_ack_is_observed_with_same_marker_never_recreated(self):
        original=self.fx.wake_policy
        def lost(*a,**kw):original(*a,**kw);raise TimeoutError('lost')
        self.fx.wake_policy=lost;self.advance()
        self.assertEqual(self.state()['stage'],'policy_attestation_observe')
        self.fx.wake_policy=original;self.advance(2)
        self.assertEqual([e[1] for e in self.effects],[True,False])
        self.assertEqual(self.effects[0][2],self.effects[1][2])

    def test_completed_task_waits_for_exact_closed_lease(self):
        self.advance();self.complete('attestation');self.closed=False;self.advance(2)
        self.assertEqual(self.state()['stage'],'policy_attestation_wait')
        self.closed=True;self.advance(3)
        self.assertEqual(self.state()['stage'],'policy_review_dispatch')

    def test_stale_artifact_or_missing_read_blocks_without_second_dispatch(self):
        for defect in ('hash','read','authority'):
            with self.subTest(defect=defect):
                self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(self.initial),))
                self.tasks=[];self.effects=[];self.advance();self.complete('attestation')
                if defect=='read':self.fx.policy_reads=lambda t:{}
                else:
                    body=json.loads(self.tasks[-1]['result']['output'])
                    body['policy_sha256']='stale' if defect=='hash' else body['policy_sha256']
                    if defect=='authority':body['execution_authorized']=True
                    self.tasks[-1]['result']['output']=json.dumps(body)
                self.advance(2);self.assertEqual(self.state()['stage'],'blocked')
                self.assertEqual(self.state()['owner'],'cto')
                self.advance(3);self.assertEqual(len(self.effects),1)

    def test_duplicate_runs_and_progress_deadline_become_owned_holds(self):
        self.advance();self.complete('attestation');self.tasks.append(copy.deepcopy(self.tasks[0]))
        self.tasks[-1]['id']='duplicate';self.advance(2)
        self.assertEqual(self.state()['category'],'policy_ambiguous_runs')
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(self.initial),))
        self.tasks=[];self.advance(3);self.advance(604)
        self.assertEqual(self.state()['category'],'policy_progress_deadline')

    def test_large_instruction_is_held_not_truncated(self):
        self.source['context']['control_files']=['x'*4000]
        self.advance();self.assertEqual(self.state()['stage'],'blocked');self.assertFalse(self.effects)

    def test_restart_after_intake_write_reconciles_same_tasks_without_new_wakeup(self):
        self.advance();self.complete('attestation');self.advance(2);self.advance(3);self.complete('review')
        stored=[]
        def uncertain(c,s,intake):
            stored.append(copy.deepcopy(intake))
            if len(stored)==1:raise TimeoutError('ack lost after durable insert')
        self.fx.persist_intake=uncertain;self.advance(4)
        self.assertEqual(self.state()['stage'],'policy_review_wait')
        self.advance(5)
        self.assertEqual(self.state()['stage'],'inputs_ready')
        self.assertEqual(stored[0],stored[1]);self.assertEqual(len(self.effects),2)

    def test_reserve_and_transient_source_observation_never_dispatch(self):
        self.fx.reserve=lambda c:False;self.advance();self.assertFalse(self.effects)
        self.assertEqual(self.state()['stage'],'policy_attestation_dispatch')
        def timeout(c,s):raise TimeoutError('read observation expired')
        self.fx.approval_source=timeout;self.advance(2);self.assertFalse(self.effects)
        self.assertEqual(self.state()['stage'],'policy_attestation_dispatch')

    def native_tables(self):
        self.con.row_factory=sqlite3.Row
        self.con.executescript('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT);'
            'CREATE TABLE leases(request_id TEXT,status TEXT);')

    def test_production_intake_revalidates_closed_planning_leases_and_is_immutable(self):
        from broker import generic_calibration_workflow as workflow
        self.native_tables();self.complete('attestation');self.complete('review')
        s={**self.initial,'stage':'policy_review_wait','attestation_task':'attestation-task',
            'attestation_wakeup':'attestation-wake','policy_wakeup':'review-wake'}
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(s),))
        for phase,actor in (('attestation','cto'),('review','lead')):
            tid=phase+'-task'
            self.con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                (tid,tid,actor,'issue:planning:'+tid,'issue'))
            self.con.execute('INSERT INTO leases VALUES(?,?)',(tid,'closed'))
        @contextmanager
        def db():
            yield self.con
            self.con.commit()
        fx=object.__new__(workflow.Effects);fx.b=SimpleNamespace(db=db)
        fx.plans=SimpleNamespace(task=lambda tid,actor:next(t for t in self.tasks if t['id']==tid),
            reads=lambda task:self.reads)
        fx.approval_source=lambda c,s:copy.deepcopy(self.source)
        intake=dict(policy=self.policy,context={**self.source['context'],
            'proposal_wakeup':'attestation-wake','review_wakeup':'review-wake'},previous=self.source['previous'],
            proposal_task='attestation-task',review_task='review-task',
            probe_job_key='author-task:calibration-inputs:'+digest(self.policy))
        fx.persist_intake(self.c,s,intake);fx.persist_intake(self.c,s,intake)
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_intakes').fetchone()[0],1)
        self.con.execute("UPDATE leases SET status='running' WHERE request_id='review-task'")
        with self.assertRaises(ValueError):fx.persist_intake(self.c,s,intake)
        self.con.execute("UPDATE leases SET status='closed'")
        self.con.execute("UPDATE native_bindings SET scope='issue:implementation:review-task' WHERE task_id='review-task'")
        with self.assertRaises(ValueError):fx.persist_intake(self.c,s,intake)

    def test_live_planning_mounts_are_four_readonly_volumes_bound_to_exact_wakeup(self):
        from broker import generic_calibration_workflow as workflow
        self.native_tables();self.c.update(candidate_volume='owned-candidate',previous_volume='owned-previous')
        self.con.execute('UPDATE generic_calibration_workflows SET config=?,state=?',
            (json.dumps(self.c),json.dumps({**self.initial,'stage':'policy_review_wait','policy_wakeup':'review-wake'})))
        self.con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
            ('req','review-task','lead','issue:planning:review-task','issue'))
        self.con.execute('INSERT INTO leases VALUES(?,?)',('req','running'))
        @contextmanager
        def db():yield self.con
        fx=SimpleNamespace(verify=lambda c:None,approval_source=lambda c,s:self.source,
            plans=SimpleNamespace(task=lambda tid,actor:dict(wakeup_id='review-wake',issue_id='issue')))
        with patch.object(workflow,'Effects',return_value=fx):
            mounts=workflow.mounts(SimpleNamespace(db=db),dict(issue_id='issue',agent_id='lead'))
            self.assertEqual(len(mounts),4);self.assertTrue(all(m['ReadOnly'] for m in mounts))
            self.assertEqual({m['Target'] for m in mounts},{'/evidence/'+k for k in ('candidate','previous','policy','controls')})
            fx.plans.task=lambda tid,actor:dict(wakeup_id='stale',issue_id='issue')
            with self.assertRaises(ValueError):workflow.mounts(SimpleNamespace(db=db),dict(issue_id='issue',agent_id='lead'))
