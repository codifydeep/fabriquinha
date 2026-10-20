import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from types import SimpleNamespace

import calibration_dependency_probe as probe
import calibration_response_contract as wire
from broker import calibration_read_recovery as recovery,generic_calibration_workflow as workflow,handoffs


class ReadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        workflow.initialize(self.con);handoffs.initialize(self.con)
        self.c=dict(issue_id='parent',author_task='author',cto='cto',reviewer='lead',criteria={'A01':'unchanged'},
            test_files=['tests/test_new.py'],prepared=dict(manifest_sha256='a'*64,test_sha256={'tests/test_new.py':'b'*64}))
        self.old=dict(stage='blocked',category='bundle_task_failed',observed_task='failed-producer',
            execution_authorized=False,delivery_approval=False)
        self.cfg=dict(source=self.c,previous_state=self.old,incident_id='prior-incident',incident_config_sha256='d'*64,
            incident_decision={'unchanged':'native'},image='sha256:'+'f'*64)
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            ('parent','author',json.dumps(self.c),json.dumps(self.old)))
        handoffs.save(self.con,'author','parent','test_first_blocked','cto',dict(calibration_prerequisite=self.old),0)
        self.measurement=dict(operation='static_calibration_dependency_probe_v1',manifest_sha256='a'*64,
            test_sha256={'tests/test_new.py':'b'*64},dependencies=[dict(module='tests/test_new.py',attribute='SCRIPT',path='app/script.js',sha256='c'*64)],
            required_paths=sorted(['/evidence/candidate/tests/test_new.py','/evidence/previous/tests/test_new.py','/evidence/candidate/app/script.js']),
            checks=probe.read_contract_experiment(),script_sha256=hashlib.sha256(Path(probe.__file__).read_bytes()).hexdigest(),
            contract_sha256=hashlib.sha256(Path(wire.__file__).read_bytes()).hexdigest(),model_calls=0,
            product_tests_executed=False,historical_cause_proven=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
        raw=json.dumps(self.measurement)
        self.job=dict(output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest(),exit_code=0,approval=False)
        self.runs=[];self.wakes=[];self.uncertain=False;self.choice='request_correction'
        def wake(cfg,s,phase,first):
            self.wakes.append((phase,first,s['marker']))
            if self.uncertain:self.uncertain=False;raise TimeoutError('ack lost')
            return {'id':phase+'-wake'}
        self.fx=SimpleNamespace(verify=lambda cfg:None,measure=lambda cfg:copy.deepcopy(self.job),failed_reads=lambda cfg:{},
            issue=lambda *args:dict(id='spike',identifier='EVAL-TEST'),reserve=lambda:True,wake=wake,
            runs=lambda *args:self.runs,validate_decisions=lambda *args:None,
            decision=lambda cfg,s,phase,t:dict(task_id=t['id'],agent_id=t['agent_id'],
                value=dict(action=self.choice,reason='Assess changed mandatory input, not historical cause',optional_files=[])),
            arm=lambda con,*args:recovery.Effects.arm(None,con,*args))
    def step(self):return recovery.advance(self.con,self.cfg,self.fx,now=10)
    def finish(self,phase):
        self.runs.append(dict(id=phase+'-task',wakeup_id=phase+'-wake',agent_id='cto' if phase=='cto' else 'lead',status='completed'))
        return self.step()
    def ready_review(self):
        self.step();self.step();self.step();self.finish('cto');return self.step()
    def arm(self):
        self.ready_review();self.finish('review');return self.step()
    def test_measured_incomplete_dependency_requires_two_independent_native_decisions(self):
        state=self.arm();self.assertEqual(state['stage'],'armed')
        current=json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
        self.assertEqual(current['stage'],'bundle_dispatch')
        receipt=recovery.qualified(self.con,self.c,current)
        self.assertEqual(receipt['previous_state'],self.old);self.assertEqual(receipt['previous_incident_decision'],self.cfg['incident_decision'])
        self.assertEqual(receipt['measurement']['required_paths'],self.measurement['required_paths'])
        for field in ('source_reset','author_retry_authorized','execution_authorized','delivery_approval'):self.assertFalse(receipt[field])
        self.assertEqual(len(self.wakes),2);self.assertEqual(self.step(),state);self.assertEqual(len(self.wakes),2)
        note=recovery.producer_instruction(self.c,receipt)
        self.assertEqual(wire.request(dict(messages=[dict(role='user',content=note)]))['required_paths'],self.measurement['required_paths'])
    def test_closed_native_hold_does_not_arm_or_repeat_a_data_submission(self):
        self.ready_review();self.choice='escalate_cto';self.finish('review')
        self.assertEqual(self.step()['stage'],'blocked');self.assertEqual(len(self.wakes),2)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]),self.old)
    def test_missing_new_evidence_is_not_a_retry_budget(self):
        self.fx.failed_reads=lambda cfg:{'/evidence/candidate/app/script.js':dict(lines=100,total_lines=100)}
        self.assertEqual(self.step()['stage'],'blocked');self.assertEqual(self.wakes,[])
    def test_stale_helper_manifest_and_forged_authority_are_rejected(self):
        self.measurement['delivery_approval']=True
        raw=json.dumps(self.measurement);self.job.update(output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(self.step()['stage'],'blocked');self.assertEqual(self.wakes,[])
    def test_unknown_wakeup_only_observes_original_marker(self):
        self.step();self.step();self.uncertain=True;self.assertEqual(self.step()['stage'],'cto_observe')
        self.step();self.assertEqual([x[1] for x in self.wakes],[True,False]);self.assertEqual(self.wakes[0][2],self.wakes[1][2])
    def test_changed_parent_or_missing_prerequisite_projection_cannot_be_armed(self):
        self.ready_review();self.finish('review')
        self.con.execute('DELETE FROM delivery_handoffs');self.con.commit()
        self.assertEqual(self.step()['stage'],'blocked')
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]),self.old)
    def test_other_failure_classes_and_already_consumed_experiments_are_not_eligible(self):
        cfg=dict(rejection=dict(diagnostic=dict(version='calibration-constraint-v2',failure_code='invalid_json')))
        s=dict(stage='blocked',category='incident_experiment_not_applicable',observed_phase='diagnosis',
            cto_decision=dict(value=dict(action='request_transport_probe',experiment='fixed_transport_probe_v1')))
        self.assertTrue(recovery.inapplicable_json_request(cfg,s))
        s['category']='incident_hold_binding_rejected';self.assertTrue(recovery.inapplicable_json_request(cfg,s))
        for extra in (dict(probe={'done':True}),dict(json_format_addendum_consumed=True),dict(observed_phase='review')):
            self.assertFalse(recovery.inapplicable_json_request(cfg,{**s,**extra}))
    def test_persisted_recovery_identity_cannot_be_replaced(self):
        self.step();changed=copy.deepcopy(self.cfg);changed['image']='replacement'
        with self.assertRaises(ValueError):recovery.advance(self.con,changed,self.fx)

    def test_interruption_after_parent_write_cannot_commit_half_an_authorization(self):
        self.ready_review();self.finish('review')
        def fail(con,*args):
            recovery.Effects.arm(None,con,*args)
            raise ValueError('interrupted between parent and recovery updates')
        self.fx.arm=fail
        self.assertEqual(self.step()['stage'],'blocked')
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]),self.old)

    def test_both_real_notes_select_the_existing_tool_free_typed_contract(self):
        from decision_schema import apply
        from typed_decision_contract import apply as typed,NAME
        state=self.ready_review();state['cto_decision']['value']['reason']='x'*1200
        for phase in ('cto','review'):
            note=recovery.instruction(self.cfg,state,phase)
            self.assertLessEqual(len(note),3800)
            body=typed(apply(dict(messages=[dict(role='user',content=note)],tools=[])))
            self.assertEqual(body['tool_choice'],dict(type='function',function=dict(name=NAME)))
            self.assertEqual(len(body['tools']),1)
            self.assertEqual(set(body['tools'][0]['function']['parameters']['properties']),{'action','reason','optional_files'})
