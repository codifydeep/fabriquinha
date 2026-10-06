import copy
import hashlib
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from broker import admission_controls_spike as spike
from broker.test_decomposition import advance, validate_result, validate_escalation


class AdmissionControlsSpikeTests(unittest.TestCase):
    def test_planning_binding_uses_native_task_not_grant_task(self):
        c=sqlite3.connect(':memory:')
        c.execute('CREATE TABLE native_bindings(request_id,task_id)')
        c.execute('CREATE TABLE grants(request_id,task_id,mode)')
        c.execute('INSERT INTO native_bindings VALUES (?,?)',('execution','native-task'))
        c.execute('INSERT INTO grants VALUES (?,?,?)',('execution','grant-task','planning'))
        self.assertEqual(spike.planning_bindings(c,'native-task'),[('execution','planning')])
        self.assertEqual(spike.planning_bindings(c,'grant-task'),[])

    def setUp(self):
        self.config=dict(kind='admission_controls_v1',root='root',unit='U3',source_task='author-task',
            issue_id='issue',cto='cto',author='author',required_files=['tests/new.py'],
            criteria={'C01':'Query clearing intervention','C02':'Stale paint intervention'},
            diagnostic_sha256='a'*64,diagnostic={'added_methods':[]})
        self.task=dict(id='cto-task',agent_id='cto',status='completed',wakeup_id='wake')
        self.reads={'/evidence/candidate/tests/new.py':dict(lines=5,total_lines=5)}
        self.decision=dict(action='propose_test_decomposition',reason='Two narrow experiments.',optional_files=[],units=[
            dict(id='U1',depends_on=[],criteria=['C01'],objective='Retain old query and assert clearing catches it.'),
            dict(id='U2',depends_on=['U1'],criteria=['C02'],objective='Paint old response and assert current DOM cannot be overwritten.')])

    def test_two_isolated_controls_are_a_plan_not_execution(self):
        proof=validate_result(self.config,self.task,self.decision,self.reads)
        self.assertFalse(proof['execution_authorized'])
        self.assertFalse(proof['delivery_approval'])
        d=copy.deepcopy(self.decision)
        d['units'][0]['criteria']=['C01','C02'];d['units'].pop()
        with self.assertRaises(ValueError):validate_result(self.config,self.task,d,self.reads)
        d=copy.deepcopy(self.decision);d['units'][1]['criteria']=['C01']
        with self.assertRaises(ValueError):validate_result(self.config,self.task,d,self.reads)

    def test_completed_cto_refusal_is_visible_without_claiming_verified_findings(self):
        d=dict(action='escalate_cto',reason='Driver prerequisites are missing.',optional_files=[],units=[])
        fx=SimpleNamespace(decomposition_proposal=lambda t:d,read_evidence=lambda t:self.reads)
        state=advance(self.config,dict(stage='pending',wakeup_id='wake',at=1),[self.task],fx,now=2)
        self.assertEqual(state['category'],'cto_scope_escalation')
        self.assertEqual(state['certificate']['owner'],'cto')
        self.assertFalse(state['certificate']['findings_verified'])
        self.assertFalse(state['certificate']['execution_authorized'])
        self.assertEqual(advance(self.config,state,[],fx,now=3),state)

    def test_failed_task_incomplete_reads_and_author_cannot_escalate_as_cto(self):
        d=dict(action='escalate_cto',reason='Missing driver.',optional_files=[],units=[])
        for task,reads in (({**self.task,'status':'failed'},self.reads),
                ({**self.task,'agent_id':'author'},self.reads),(self.task,{})):
            with self.assertRaises(ValueError):validate_escalation(self.config,task,d,reads)
    def test_focused_note_does_not_repeat_general_harness_repair(self):
        effects=SimpleNamespace(ensure_wakeup=Mock(return_value={'id':'wake'}),remaining_calls=lambda:128)
        state=advance(self.config,{'stage':'pending','deterministic_reads':True},[],effects,now=1)
        note=effects.ensure_wakeup.call_args.args[-1]
        self.assertIn('EXACTLY TWO',note)
        self.assertIn('Do not repeat whole-harness repair',note)
        self.assertIn('DELIVERY_DETERMINISTIC_READ_V1',note)
        self.assertLessEqual(len(note),3900)
        self.assertEqual(state['wakeup_id'],'wake')

    def test_no_second_wakeup_after_failure_or_ready_plan(self):
        effects=SimpleNamespace(ensure_wakeup=Mock(return_value={'id':'wake'}),remaining_calls=lambda:128,
            decomposition_proposal=lambda t:self.decision,read_evidence=lambda t:self.reads)
        state=advance(self.config,{'stage':'pending'},[],effects,now=1)
        ready=advance(self.config,state,[self.task],effects,now=2)
        self.assertEqual(ready['stage'],'proposal_ready')
        self.assertEqual(advance(self.config,ready,[],effects,now=3),ready)
        failed=advance(self.config,state,[],effects,now=1802)
        self.assertEqual(failed['stage'],'blocked')
        self.assertEqual(advance(self.config,failed,[],effects,now=1803),failed)
        effects.ensure_wakeup.assert_called_once()

    def test_paused_route_current_incident_and_exact_red_are_mandatory(self):
        from broker.source_harness_completion import proof_digest
        c=sqlite3.connect(':memory:')
        for sql in ('CREATE TABLE incremental_checkpoints(source_task,state)',
                'CREATE TABLE delivery_routes(issue_id,config)',
                'CREATE TABLE incremental_runtime_incidents(source_task,receipt)',
                'CREATE TABLE test_first_red(issue_id,receipt)',
                'CREATE TABLE source_harness_checks(issue_id,manifest_sha256,receipt)'):
            c.execute(sql)
        u=dict(revision=5,stage='awaiting_red',admission_hold={'held':True},binding={'issue_id':'issue'})
        route=dict(enabled=False,author='author',cto='cto')
        incident=json.dumps({'category':'incomplete_source_harness_repair'})
        proof={'added_methods':[],'removed_methods':[]}
        config={**self.config,'incident_sha256':hashlib.sha256(incident.encode()).hexdigest(),
            'diagnostic_sha256':proof_digest(proof)}
        c.execute('INSERT INTO incremental_checkpoints VALUES (?,?)',('root',json.dumps({'units':{'U3':u}})))
        c.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(route)))
        c.execute('INSERT INTO incremental_runtime_incidents VALUES (?,?)',('root',incident))
        c.execute('INSERT INTO test_first_red VALUES (?,?)',('issue',json.dumps({'task_id':'author-task','red':{'manifest_sha256':'m'}})))
        c.execute('INSERT INTO source_harness_checks VALUES (?,?,?)',('issue','m',json.dumps(proof)))
        spike.verify_current(c,config)
        for changed in ({**route,'enabled':True},{**route,'cto':'author'}):
            c.execute('UPDATE delivery_routes SET config=?',(json.dumps(changed),))
            with self.assertRaises(ValueError):spike.verify_current(c,config)
        c.execute('UPDATE delivery_routes SET config=?',(json.dumps(route),))
        c.execute('UPDATE test_first_red SET receipt=?',(json.dumps({'task_id':'other','red':{'manifest_sha256':'m'}}),))
        with self.assertRaises(ValueError):spike.verify_current(c,config)
