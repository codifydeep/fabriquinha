import copy
import json
import sqlite3
import unittest
from broker import calibration_incidents as incidents,handoffs,generic_calibration_workflow as workflow
from generic_harness_calibration import digest
from calibration_transport_probe import source_hashes,run


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        handoffs.initialize(self.con);workflow.initialize(self.con);incidents.initialize(self.con)
        self.c=dict(issue_id='00000000-0000-4000-8000-000000000001',author_task='00000000-0000-4000-8000-000000000002',
            cto='00000000-0000-4000-8000-000000000003',reviewer='00000000-0000-4000-8000-000000000004',
            prepared=dict(manifest_sha256='a'*64),calibration_engine='unittest_path_fixtures_v2')
        self.s=dict(stage='blocked',category='bundle_task_failed',observed_task='00000000-0000-4000-8000-000000000005',
            wakeup_id='00000000-0000-4000-8000-000000000006',execution_authorized=False,delivery_approval=False)
        self.task=dict(id=self.s['observed_task'],wakeup_id=self.s['wakeup_id'],agent_id=self.c['cto'],issue_id=self.c['issue_id'],status='failed')
        self.binding=dict(request_id='00000000-0000-4000-8000-000000000007',task_id=self.task['id'],status='closed',
            agent_id=self.c['cto'],issue_id=self.c['issue_id'],scope='workspace:cto:planning:'+self.task['id'])
        self.rejection=dict(operation='structured_validator_rejection_v1',execution_id=self.binding['request_id'],call_number=1,
            category='calibration_response_invalid',diagnostic=dict(version='calibration-constraint-v1',category='invalid_transport_or_tool',
                constraints=[],fields=[],missing_fields=[],upstream_sha256='b'*64),response_forwarded=False,worker_tool_executed=False,
            execution_authorized=False,delivery_approval=False)
        self.cfg=incidents.prepare(self.c,self.s,self.task,self.binding,self.rejection,source_hashes())
        self.key=self.cfg['incident_id']
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            (self.c['issue_id'],self.c['author_task'],json.dumps(self.c),json.dumps(self.s)))
        handoffs.save(self.con,self.c['author_task'],self.c['issue_id'],'test_first_blocked',self.c['cto'],
            dict(calibration_prerequisite=self.s,error='generic_calibration_prerequisite:bundle_task_failed'),0)
        incidents.register(self.con,self.cfg);self.effects=[];self.runs=[];self.uncertain=False;parent=self
        self.proof=run();self.result=dict(output=json.dumps(self.proof),output_sha256=__import__('hashlib').sha256(json.dumps(self.proof).encode()).hexdigest(),
            container_id='probe',image='sha256:'+'c'*64)
        class Effects:
            def verify(_,cfg):pass
            def reserve(_):return True
            def issue(_,cfg,first):parent.effects.append(('issue',first));return dict(id='child',identifier='EVAL-TEST')
            def wake(_,cfg,s,phase,first):
                parent.effects.append(('wake',phase,first,s['marker']))
                if parent.uncertain:parent.uncertain=False;raise TimeoutError()
                return dict(id=phase+'-wake')
            def runs(_,cfg,s):return parent.runs
            def decision(_,cfg,s,phase,task):
                from calibration_incident_contract import context
                ctx=incidents.context(cfg,s,phase)
                value=dict(action='request_transport_probe' if phase=='diagnosis' else 'sponsor_data_submission',
                    incident_sha256=ctx['incident_sha256'],reason='Measured probe, not a claim about historical cause',
                    experiment='fixed_transport_probe_v1',historical_cause_proven=False,author_retry_authorized=False,
                    execution_authorized=False,delivery_approval=False)
                if phase=='review':value.update(proposal_sha256=ctx['proposal_sha256'],probe_sha256=ctx['probe_sha256'])
                return dict(value=value,task_id=task['id'],agent_id=task['agent_id'],execution_id=phase+'-execution')
            def probe(_,cfg,s):parent.effects.append(('probe',));return parent.result
        self.fx=Effects()

    def advance(self,now=1):return incidents.advance(self.con,self.key,self.fx,now=now)

    def finish_phase(self,phase):
        self.runs=[dict(id=phase+'-task',agent_id=self.c['cto'] if phase=='diagnosis' else self.c['reviewer'],
            issue_id='child',wakeup_id=phase+'-wake',status='completed')]
        return self.advance()

    def test_cto_real_probe_independent_review_and_new_submission_not_author_retry(self):
        self.advance();self.advance();self.finish_phase('diagnosis');self.advance();self.advance();self.finish_phase('review')
        state=self.advance();self.assertEqual(state['stage'],'resubmission_sponsored')
        _,source=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        self.assertEqual(source['stage'],'bundle_dispatch');self.assertIn('incident_resume_sha256',source)
        self.assertFalse(state['sponsorship']['author_restarted']);self.assertFalse(state['sponsorship']['delivery_approval'])
        before=list(self.effects);self.advance();self.assertEqual(self.effects,before)

    def test_lost_dispatch_ack_is_observed_without_second_create(self):
        self.advance();self.uncertain=True;self.advance();self.advance()
        wakes=[x for x in self.effects if x[0]=='wake']
        self.assertEqual([x[2] for x in wakes],[True,False]);self.assertEqual(wakes[0][3],wakes[1][3])

    def test_same_failure_class_is_not_a_new_budget_even_with_new_response_hash(self):
        cfg=copy.deepcopy(self.cfg);cfg['rejection']['diagnostic']['upstream_sha256']='c'*64
        cfg['failed_execution']='different';cfg['failed_task']='later'
        incidents.register(self.con,cfg)
        self.assertEqual(self.advance()['stage'],'blocked');self.assertEqual(self.effects,[])

    def test_changed_frozen_source_or_failed_probe_cannot_resume(self):
        self.advance();self.advance();self.finish_phase('diagnosis')
        self.result['output_sha256']='0'*64
        self.assertEqual(self.advance()['stage'],'blocked')
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]),self.s)

    def test_parent_projects_the_actual_reviewer_and_lookup_errors_are_deduplicated(self):
        self.advance();self.advance();self.finish_phase('diagnosis');self.advance()
        p=incidents.projection(self.con,self.c['issue_id'],self.c['author_task'],self.s)
        self.assertEqual(p['owner'],self.c['reviewer']);self.assertEqual(p['stage'],'review_dispatch')
        incidents.enrollment_error(self.con,self.c,self.s,TimeoutError('private detail'))
        incidents.enrollment_error(self.con,self.c,self.s,TimeoutError('private detail'))
        self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_incident_lookup_events').fetchone()[0],1)
        p=incidents.projection(self.con,self.c['issue_id'],self.c['author_task'],self.s)
        self.assertEqual(p['observation_error'],'TimeoutError');self.assertNotIn('private',json.dumps(p))

    def test_stale_sponsorship_cannot_resume_a_changed_source(self):
        self.advance();self.advance();self.finish_phase('diagnosis');self.advance();self.advance();self.finish_phase('review')
        changed={**self.c,'prepared':{'manifest_sha256':'0'*64}}
        self.con.execute('UPDATE generic_calibration_workflows SET config=?',(json.dumps(changed),));self.con.commit()
        self.assertEqual(self.advance()['stage'],'blocked')
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]),self.s)
