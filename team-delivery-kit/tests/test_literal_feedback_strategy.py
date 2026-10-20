import copy
import json
import time
import unittest
from unittest.mock import patch
from broker import literal_feedback_strategy as strategy,literal_maintenance_workflow as flow
from broker import author_feedback_admission as admission,literal_maintenance_effects as lane
from broker import test_revision_review
import test_author_feedback_admission as fixture
from test_artifact_schema import apply as artifact_contract


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.AdmissionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.source=fixture.identity(88);self.parent_issue=fixture.identity(77)
        self.cfg=dict(source=dict(author_task=self.source,issue_id=fixture.identity(76)),author=self.f.author,cto=self.f.cto,
            reviewer=self.f.lead,parent_issue_id=fixture.identity(75),test_path=self.f.p['test_path'],
            counterexample=dict(facts=dict(assertion_bindings=self.f.p['expected'])))
        self.held=dict(stage='blocked',category='maintenance_evidence_replan_rejected',revision=2,source_reset=False,delivery_approval=False,
            issue_id=self.parent_issue,history=[dict(author_task=fixture.identity(89+i),snapshot=dict(volume='old-'+str(i)),inspection={}) for i in range(2)]+[
                dict(author_task=self.f.source,snapshot=dict(volume=self.f.p['previous_volume']),inspection=dict(
                    candidate_manifest_sha256='b'*64,structure=dict(candidate_test_sha256='f'*64)))])
        with self.f.db() as c:
            flow.initialize(c);c.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',
                (self.source,json.dumps(self.cfg,sort_keys=True),json.dumps(self.held,sort_keys=True)))
        self.q=copy.deepcopy(self.f.q);self.q['identity']['namespace']=self.f.b.PREFIX
        self.seal=dict(stage='sealed',operation_id='operator-maintenance')
        for target,value in [('maintenance.current',lambda c:self.seal),('maintenance.native_active',lambda b:[]),('authenticate_parent',lambda *a:None)]:
            p=patch('broker.literal_feedback_strategy.'+target,side_effect=value);p.start();self.addCleanup(p.stop)
        p=patch.dict('os.environ',BROKER_LITERAL_AUTHOR_FEEDBACK_IMAGE=self.f.p['image'],BROKER_AUTHOR_FEEDBACK_WORKER_IMAGE=self.f.p['worker_image'])
        p.start();self.addCleanup(p.stop)
        parent=self;self.posts=[];self.uncertain=False;self.exists=False
        class Issues:
            def __init__(self,settings):pass
            def request(self,path):return dict(project_id='same-project')
            def ensure(self,desired,allow_create):
                parent.posts.append(allow_create)
                if allow_create:
                    parent.exists=True
                    if parent.uncertain:parent.uncertain=False;raise TimeoutError()
                if not parent.exists:return None
                return dict(desired,id=parent.f.issue,identifier='TEST-feedback')
        p=patch.object(strategy,'NativeIssues',Issues);p.start();self.addCleanup(p.stop)

    def enroll(self):return strategy.enroll(self.f.b,self.source,self.q,self.seal['operation_id'])

    def child(self):
        with self.f.db() as c:
            return tuple(map(json.loads,c.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(self.f.source,)).fetchone()))

    def test_separate_registration_is_idempotent_and_preserves_exhausted_state(self):
        receipt=self.enroll();cfg,s=self.child()
        self.assertEqual(s['stage'],'plan_dispatch');self.assertEqual(s['history'],[])
        self.assertEqual(cfg['workflow_key'],self.f.source);self.assertFalse(receipt['native_author_started'])
        with self.f.db() as c:
            self.assertEqual(json.loads(c.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(self.source,)).fetchone()[0]),self.held)
        self.assertEqual(self.enroll(),receipt);self.assertEqual(self.posts,[True])

    def test_registration_requires_the_callers_exact_sealed_operation(self):
        with self.assertRaises(ValueError):strategy.enroll(self.f.b,self.source,self.q,'different-operation')
        self.assertEqual(self.posts,[])

    def test_lost_metadata_ack_observes_exact_intent_without_second_post(self):
        self.uncertain=True
        with self.assertRaises(TimeoutError):self.enroll()
        receipt=self.enroll();self.assertEqual(receipt['issue_id'],self.f.issue);self.assertEqual(self.posts,[True,False])

    def test_changed_predecessor_rejected_but_notification_failure_is_not_authority(self):
        self.enroll();cfg,_=self.child()
        with self.f.db() as c:
            changed=dict(self.held,notification_error='TimeoutError')
            c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(changed),self.source))
        strategy.verify(self.f.b,cfg)
        with self.f.db() as c:
            changed['history']=[];c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(changed),self.source))
        with self.assertRaises(ValueError):strategy.verify(self.f.b,cfg)

    def test_live_prompt_cannot_inherit_legacy_forced_patch_or_historical_context(self):
        self.enroll();cfg,_=self.child();self.f.p=cfg['feedback_strategy']['policy'];self.f.q=self.q
        # Complete native authority records are fixture data here; real model
        # execution remains a separate qualification requirement.
        self.f.tasks.clear()
        with self.f.db() as c:
            for table in ('native_bindings','leases','grants'):c.execute('DELETE FROM '+table)
        self.f.add_planner('cto',self.f.approvals['cto'],self.f.cto)
        proposal=admission.approval(self.f.b,self.f.p,'cto',self.f.approvals['cto'])
        self.f.add_planner('sponsor',self.f.approvals['sponsor'],self.f.lead,proposal)
        self.f.arm();self.f.start();self.f.b.implementation_phase=lambda issue:'tests_only'
        with self.f.db() as c:
            c.execute('UPDATE leases SET status=? WHERE request_id=?',('running',self.f.request))
            s=dict(stage='author_wait',decisions=dict(plan=dict(receipt=proposal),permit={}),revision=0,history=[],
                phase_started=time.time(),wakeup_id=fixture.identity(32),marker=admission.marker(self.f.p,'author'),issue_id=self.f.issue)
            c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(s),self.f.source))
            c.execute('CREATE TABLE delivery_routes(issue_id,config)');c.execute('INSERT INTO delivery_routes VALUES(?,?)',
                (self.f.issue,json.dumps(dict(enabled=False,test_first=True,author=self.f.author,test_first_files=[cfg['test_path']]))))
            c.execute('CREATE TABLE test_revision_trials(issue_id,config)');c.execute('INSERT INTO test_revision_trials VALUES(?,?)',
                (self.f.issue,json.dumps(dict(harness_maintenance_only=True,literal_maintenance=dict(source_task=flow.workflow_key(cfg),config_sha256=admission.digest(cfg))))))
            c.execute('CREATE TABLE issue_editables(issue_id,path)')
            c.executemany('INSERT INTO issue_editables VALUES(?,?)',[(self.f.issue,p) for p in ('/workspace/tests/test.py','/workspace/app.js')])
        frame=dict(method='session/prompt',params=dict(prompt=[dict(type='text',text='UNTRUSTED CALLER')]))
        with patch.object(lane,'STATE',self.f.b.STATE):
            rendered=strategy.prompt(self.f.b,frame,dict(id=self.f.issue,description='HISTORICAL'),self.f.tasks[self.f.task])
        text=rendered['params']['prompt'][0]['text']
        self.assertIn('/feedback/current.json',text);self.assertNotIn('UNTRUSTED CALLER',text);self.assertNotIn('HISTORICAL',text)
        self.assertNotIn('DELIVERY_TEST_ARTIFACT_V1:',text)
        body=dict(messages=[dict(role='user',content=text)],tools=[])
        self.assertEqual(artifact_contract(copy.deepcopy(body)),body)
        with self.f.db() as c:c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(dict(s,stage='blocked')),self.f.source))
        with patch.object(lane,'STATE',self.f.b.STATE),self.assertRaises(ValueError):
            strategy.prompt(self.f.b,frame,dict(id=self.f.issue),self.f.tasks[self.f.task])

    def prepare_metadata_failure(self):
        self.enroll();cfg,_=self.child();self.f.p=cfg['feedback_strategy']['policy']
        self.f.tasks.clear()
        with self.f.db() as c:
            for table in ('native_bindings','leases','grants'):c.execute('DELETE FROM '+table)
        self.f.add_planner('cto',self.f.approvals['cto'],self.f.cto)
        cto=admission.approval(self.f.b,self.f.p,'cto',self.f.approvals['cto'])
        self.f.add_planner('sponsor',self.f.approvals['sponsor'],self.f.lead,cto)
        task=self.f.tasks[self.f.approvals['sponsor']];value=json.loads(task['result']['output']);value['reason']='x'*336
        task['result']['output']=json.dumps(value,sort_keys=True)
        sponsor=admission.approval(self.f.b,self.f.p,'sponsor',self.f.approvals['sponsor'],cto)
        decisions={}
        for phase,role,proof in (('plan','cto',cto),('permit','sponsor',sponsor)):
            r={k:v for k,v in proof.items() if k!='request_id'};r.update(execution_id=proof['request_id'],read_evidence={})
            decisions[phase]=dict(receipt=r,wakeup_id=proof['wakeup_id'],marker=admission.marker(self.f.p,role))
        state=dict(stage='blocked',category='maintenance_evidence_rejected',owner=self.f.cto,phase_started=123,
            revision=0,history=[],decisions=decisions,source_reset=False,delivery_approval=False,
            last_error=dict(phase='prepare',type='ValueError',sha256='e'*64))
        with self.f.db() as c:
            c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),self.f.source))
            test_revision_review.initialize(c)
            c.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',(self.f.issue,cfg['parent_issue_id'],
                json.dumps(dict(literal_maintenance=dict(source_task=self.f.source,config_sha256=admission.digest(cfg)))),'{}'))
        return cfg,state

    def test_metadata_recovery_preserves_decisions_history_and_deadline_without_replay(self):
        cfg,failed=self.prepare_metadata_failure()
        receipt=strategy.recover_metadata_bound(self.f.b,self.f.source,self.seal['operation_id'])
        self.assertEqual(receipt['previous_state'],failed);self.assertEqual(receipt['reason_characters'],336)
        self.assertEqual(receipt['typed_reason_limit'],900);self.assertFalse(receipt['author_retry_authorized'])
        _,state=self.child();self.assertEqual(state['stage'],'prepare')
        for field in ('phase_started','revision','history','decisions'):self.assertEqual(state[field],failed[field])
        self.assertNotIn('last_error',state);self.assertNotIn('category',state)
        self.assertEqual(strategy.recover_metadata_bound(self.f.b,self.f.source,self.seal['operation_id']),receipt)
        with self.f.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM literal_feedback_metadata_recoveries').fetchone()[0],1)
            self.assertEqual(json.loads(c.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(self.source,)).fetchone()[0]),self.held)

    def test_metadata_recovery_cannot_ignore_an_author_start_changed_native_authority_or_wrong_maintenance(self):
        cfg,failed=self.prepare_metadata_failure()
        with self.assertRaises(ValueError):strategy.recover_metadata_bound(self.f.b,self.f.source,'wrong-operation')
        with self.f.db() as c:c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
            (json.dumps(dict(failed,author_task='already-started')),self.f.source))
        with self.assertRaises(ValueError):strategy.recover_metadata_bound(self.f.b,self.f.source,self.seal['operation_id'])
        with self.f.db() as c:c.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(failed),self.f.source))
        self.f.tasks[self.f.approvals['sponsor']]['status']='failed'
        with self.assertRaises(ValueError):strategy.recover_metadata_bound(self.f.b,self.f.source,self.seal['operation_id'])
        self.assertEqual(self.child()[1],failed)
