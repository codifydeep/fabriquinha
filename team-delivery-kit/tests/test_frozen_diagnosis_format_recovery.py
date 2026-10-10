import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
from broker import frozen_diagnosis_format_recovery as r,handoffs


class FrozenDiagnosisFormatTests(unittest.TestCase):
    def evidence(self):
        source='11111111-1111-4111-8111-111111111111';failed='22222222-2222-4222-8222-222222222222'
        issue='33333333-3333-4333-8333-333333333333';execution='44444444-4444-4444-8444-444444444444'
        paths=['app/static/app.js','tests/test_new.py'];sha='a'*64;schema='b'*64
        data=dict(validation_failure=dict(category='executed_test_failure',phase='frozen_green',exit_code=1,
            source_task=source,volume='snapshot',tests_executed=4,output_sha256=sha,diagnostic_read_files=paths),
            error='recipient_execution_failed',artifact_diagnosis=True,failed_dispatch_stage='diagnose_cto',
            recipient_task=failed,target='cto',wakeup_id='old',diagnostic_revision='revision',attempts=2,
            instruction='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'+
            ''.join('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/'+p+'\n' for p in paths))
        event=dict(event='model_proxy_request',status=200,execution_id='probe',require_parameters=True,
            routing_compatibility='haiku_named_tool_v1',upstream_require_parameters=False,tool_count=1,
            decision_adapter='validated_typed_decision_adapter_v1',decision_output_sha256=sha,optional_files_format_feedback=True)
        receipt=dict(operation='validated_typed_decision_adapter_v1',output_sha256=sha,schema_sha256=schema,
            model_values_preserved=True,worker_tool_executed=False,delivery_approval=False)
        sources={name:'c'*64 for name in ('model_proxy','typed_decision_contract','technical_optional_files_feedback')}
        q=dict(operation='provider_optional_files_transport_qualification_v1',actual_artifact_read=False,
            delivery_approval=False,author_retry_authorized=False,test_change_authorized=False,
            optional_feedback_enabled=True,proxy_image='image',event=event,adapter_receipt=receipt,
            execution_id='probe',response_sha256=sha,optional_sources=sources,
            routing_sha256='e982dafa69291d7efe979081e6594ef4d3bc9fa2bd321d4be2dba1d6b87ec668')
        return dict(row=dict(source_task=source,issue_id=issue,stage='technical_decision_required',owner='cto',data=json.dumps(data),updated=1),
            route=dict(issue_id=issue,enabled=True,author='author',cto='cto',minimum_calls=8),
            source=dict(id=source,agent_id='author',status='completed'),
            failed=dict(id=failed,agent_id='cto',status='failed',failure_reason='agent_error.provider_server_error',wakeup_id='old'),
            qualification=q,rejection=dict(operation='rejected_typed_decision_adapter_v1',category='typed_schema_maxItems',
                delivery_approval=False,worker_tool_executed=False,upstream_sha256=sha,
                constraint_diagnostic=dict(constraints=['maxItems'],root_constraints=['maxItems'],locations=['optional_file_count'],schema_sha256=schema)),
            binding=dict(request_id=execution,agent_id='cto',issue_id=issue,status='closed',scope='w:cto:planning:'+failed),
            snapshot=dict(task_id=source,status='complete',volume='snapshot'),job=dict(stage='complete',approval=False,
                result=dict(exit_code=1,output_sha256=sha,approval=False)),job_task=source,job_kind='suite',
            reads={'/evidence/candidate/'+p:dict(lines=10,total_lines=10) for p in paths},expected_sources=sources,
            latest_author=source,proxy_image='image',consumed=False,active=False,pending=False,remaining=8)

    def test_produces_intent_only_preserves_full_history_and_frozen_failure(self):
        e=self.evidence();before=copy.deepcopy(e);updated,proof=r.prepare(e)
        self.assertEqual(e,before)
        self.assertEqual(updated['attempts'],2)
        self.assertEqual(updated['validation_failure'],json.loads(e['row']['data'])['validation_failure'])
        self.assertEqual(proof['previous_handoff'],e['row'])
        self.assertFalse(proof['author_retry_authorized']);self.assertFalse(proof['test_change_authorized'])
        self.assertFalse(proof['delivery_approval'])
        self.assertEqual(updated['dispatch_stage'],'diagnose_cto')
        self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/previous/tests/test_new.py',updated['instruction'])
        self.assertNotIn('wakeup_id',updated);self.assertNotIn('recipient_task',updated)

    def test_no_recovery_for_changed_identity_evidence_active_or_consumed_incidents(self):
        changes=[('row','stage','approved'),('row','owner','author'),('route','enabled',False),
            ('route','cto','author'),('source','status','failed'),('failed','status','completed'),
            ('failed','wakeup_id','other'),('binding','status','running'),('snapshot','volume','other'),
            ('job','stage','running'),('rejection','category','typed_schema_maxLength'),
            ('qualification','proxy_image','other'),('qualification','delivery_approval',True)]
        for group,key,value in changes:
            e=self.evidence();e[group][key]=value
            with self.subTest(group=group,key=key),self.assertRaises(ValueError):r.prepare(e)
        for key,value in [('active',True),('pending',True),('consumed',True),('remaining',7),('reads',{}),
                          ('job_kind','structure'),('latest_author','other'),('expected_sources',{})]:
            e=self.evidence();e[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):r.prepare(e)
        for field,value in [('constraints',['maxItems','enum']),('locations',['finding_location_selection']),('schema_sha256','c'*64)]:
            e=self.evidence();e['rejection']['constraint_diagnostic'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):r.prepare(e)

    def test_atomic_transition_is_once_only_and_restart_never_reopens_it(self):
        e=self.evidence();updated,proof=r.prepare(e)
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;self.addCleanup(c.close)
        handoffs.initialize(c);c.execute('CREATE TABLE leases(status TEXT)')
        row=e['row'];handoffs.save(c,row['source_task'],row['issue_id'],row['stage'],row['owner'],json.loads(row['data']),row['updated'])
        original=handoffs.load(c,row['source_task'])
        self.assertTrue(r.apply_transition(c,original,e['route'],updated,proof,2));c.commit()
        self.assertEqual(handoffs.load(c,row['source_task'])['stage'],'dispatch_intent')
        self.assertFalse(r.apply_transition(c,original,e['route'],updated,proof,3))
        current=handoffs.load(c,row['source_task']);handoffs.save(c,row['source_task'],row['issue_id'],'technical_decision_required','cto',json.loads(current['data']),4)
        self.assertFalse(r.apply_transition(c,handoffs.load(c,row['source_task']),e['route'],updated,proof,5))
        self.assertEqual(c.execute('SELECT count(*) FROM frozen_diagnosis_format_recoveries').fetchone()[0],1)

    def test_race_or_active_lease_cannot_consume_transition(self):
        for drift in ('row','lease'):
            e=self.evidence();updated,proof=r.prepare(e);c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
            self.addCleanup(c.close);handoffs.initialize(c);c.execute('CREATE TABLE leases(status TEXT)');row=e['row']
            handoffs.save(c,row['source_task'],row['issue_id'],row['stage'],row['owner'],json.loads(row['data']),row['updated'])
            original=handoffs.load(c,row['source_task'])
            if drift=='row':c.execute('UPDATE delivery_handoffs SET updated=9')
            else:c.execute('INSERT INTO leases VALUES (?)',('running',))
            with self.assertRaises(ValueError):r.apply_transition(c,original,e['route'],updated,proof,2)
            self.assertEqual(c.execute('SELECT count(*) FROM frozen_diagnosis_format_recoveries').fetchone()[0],0)

    def test_failed_atomic_save_rolls_back_consumption_and_keeps_original_incident(self):
        e=self.evidence();updated,proof=r.prepare(e);c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        self.addCleanup(c.close);handoffs.initialize(c);c.execute('CREATE TABLE leases(status TEXT)')
        c.execute('CREATE TABLE frozen_diagnosis_format_recoveries(source_task TEXT PRIMARY KEY,proof TEXT)')
        row=e['row'];handoffs.save(c,row['source_task'],row['issue_id'],row['stage'],row['owner'],json.loads(row['data']),row['updated'])
        original=handoffs.load(c,row['source_task'])
        with self.assertRaises(RuntimeError),patch.object(handoffs,'save',side_effect=RuntimeError('interrupted')):
            with c:r.apply_transition(c,original,e['route'],updated,proof,2)
        self.assertEqual(handoffs.load(c,row['source_task']),original)
        self.assertEqual(c.execute('SELECT count(*) FROM frozen_diagnosis_format_recoveries').fetchone()[0],0)
