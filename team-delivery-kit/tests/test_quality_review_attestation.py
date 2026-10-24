"""Controller/native fixture attestation tests, not real-agent qualification."""
import copy
import hashlib
import json
import unittest
from unittest.mock import Mock,patch
from broker import quality_review_attestation as attest,read_stream_receipts
from broker import acp_startup
import test_quality_review_launch as launch_fixture
import test_quality_test_review as review_fixture
import test_quality_lifecycle_enrollment as enrollment_fixture


class QualityReviewAttestationTests(unittest.TestCase):
    def setUp(self):
        self.files={'AGENTS.md':b'Preserve tests\n','app.py':b'VALUE=0\n',
            'tests/test_old.py':b'import unittest, app\nclass Old(unittest.TestCase):\n def test_old(self): self.assertGreaterEqual(app.VALUE, 0)\n',
            'tests/test_new.py':b'import unittest, app\n# new expectation\nclass New(unittest.TestCase):\n def test_new(self): self.assertEqual(app.VALUE, 1)\n'}
        def factory():
            f=review_fixture.QualityTestReviewTests();f.snapshot_files=self.files;return f
        original=enrollment_fixture.QualityEnrollmentTests.setUp
        def enrollment_setup(enrolled):
            original(enrolled)
            enrolled.plan['baseline_tests']['tests/test_old.py']=hashlib.sha256(self.files['tests/test_old.py']).hexdigest()
        f=launch_fixture.QualityReviewLaunchTests();f.review_fixture_factory=factory
        with patch.object(enrollment_fixture.QualityEnrollmentTests,'setUp',enrollment_setup):f.setUp()
        self.addCleanup(f.doCleanups);self.f=f;self.b=f.b;self.source=f.f.source
        self.request=f.request
        f.call();row,binding=f.rows();result=acp_startup.advance_worker(self.b,row,binding)
        with self.b.db() as con:
            acp_startup.initialize(con)
            con.execute('INSERT INTO acp_startups VALUES(?,?)',(self.request,json.dumps(dict(stage='transport_intent'))))
        with patch('broker.acp_transport.Transport',return_value=Mock()):
            f.call_transport=lambda:launch_fixture.launch.open_transport(self.b,row,result,binding['scope'])
            f.call_transport()
        with self.b.db() as con:
            con.execute('CREATE TABLE acp_events(request_id TEXT,method TEXT,session_id TEXT,success INTEGER)')
            con.execute('CREATE TABLE acp_sessions(scope TEXT,session_id TEXT,PRIMARY KEY(scope,session_id))')
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'session'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(self.request,method,'session',1))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(self.request,))
        context,_=launch_fixture.launch.review.load(self.b,self.source);packet=context['packet']
        self.verdict=dict(action='approve_tests',reason='All frozen acceptance criteria are covered.',
            manifest_sha256=packet['manifest_sha256'],plan_sha256=packet['plan_sha256'],red_sha256=packet['red_sha256'],
            criteria=packet['plan']['criteria'],findings=[])
        f.record.update(status='completed',result=dict(output=json.dumps(self.verdict)))
        self.pages=[]
        for index,(path,raw) in enumerate(self.files.items()):
            content='\n'.join(str(n)+'|'+line for n,line in enumerate(raw.decode().splitlines(),1))
            total=len(raw.decode().splitlines());identifier='read-'+str(index)
            frames=[dict(method='session/update',params=dict(update=update)) for update in (
                dict(sessionUpdate='tool_call',toolCallId=identifier,kind='read',title='read: /delivery/'+path),
                dict(sessionUpdate='tool_call_update',toolCallId=identifier,kind='read',status='completed',
                    content=[dict(type='content',content=dict(type='text',text=f'Read /delivery/{path} (from line 1, limit 100) — {total} total lines\n\n```\n{content}\n```'))]))]
            self.pages+=frames
        with self.b.db() as con:read_stream_receipts.store(con,binding,self.pages,'review')
        p=patch.object(attest.native,'issue_task_runs',return_value=[f.f.capture.native,f.record]);p.start();self.addCleanup(p.stop)

    def call(self):return attest.observe(self.b,self.source)

    def update_verdict(self,**changes):
        self.verdict.update(changes);self.f.record['result']['output']=json.dumps(self.verdict)

    def test_actual_bound_reads_and_native_verdict_freeze_only_exact_tests(self):
        receipt=self.call()
        self.assertEqual(receipt['stage'],'tests_frozen')
        self.assertTrue(receipt['tests_approved']);self.assertFalse(receipt['execution_authorized'])
        self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(receipt['owner'],self.f.f.e.author)
        self.assertEqual(set(receipt['reads']),{'/delivery/'+p for p in self.files})
        with patch.object(attest.native,'task_record',side_effect=AssertionError('durable terminal readback')):
            self.assertEqual(self.call(),receipt)

    def test_textual_claim_or_native_ui_messages_cannot_replace_actual_reads(self):
        with self.b.db() as con:con.execute('DELETE FROM observed_read_stream')
        with patch.object(attest.native,'task_messages',return_value=[dict(type='text',content='I read all files')]):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['owner'],self.b.QUALITY_CTO)
        self.assertFalse(result['tests_approved'])

    def test_obsolete_manifest_or_plan_cannot_approve_latest_tests(self):
        self.update_verdict(manifest_sha256='0'*64)
        result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertFalse(result['tests_approved'])

    def test_review_not_completed_or_lease_not_closed_cannot_freeze(self):
        self.f.record['status']='running'
        with self.assertRaises(attest.validation_job.Pending):self.call()
        self.f.record['status']='completed'
        with self.b.db() as con:con.execute("UPDATE leases SET status='running' WHERE request_id=?",(self.request,))
        with self.assertRaises(attest.validation_job.Pending):self.call()

    def test_review_identity_or_wakeup_drift_goes_to_cto_not_ceo(self):
        self.f.record['wakeup_id']=self.source
        result=self.call();self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['owner'],self.b.QUALITY_CTO)

    def test_missing_worker_inspection_cannot_be_replaced_by_read_only_claim(self):
        with self.b.db() as con:con.execute('DELETE FROM worker_policy_observations')
        result=self.call();self.assertEqual(result['stage'],'technical_blocked')

    def test_concrete_changes_return_to_original_author_without_weakening_approval(self):
        finding=dict(criterion='A01',path='tests/test_new.py',test='__module__',line=2,
            quote='new expectation',expected='A meaningful assertion',observed='Only fixture text')
        self.update_verdict(action='request_changes',reason='A01 lacks an assertion.',findings=[finding])
        result=self.call();self.assertEqual(result['stage'],'changes_requested')
        self.assertEqual(result['owner'],self.f.f.e.author)
        self.assertFalse(result['tests_approved']);self.assertFalse(result['execution_authorized'])

    def test_unobserved_finding_quote_or_missing_findings_is_not_a_valid_rejection(self):
        self.update_verdict(action='request_changes',findings=[])
        self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_full_reads_do_not_repair_changes_without_findings_and_expose_fixed_category(self):
        self.update_verdict(action='request_changes',findings=[],reason='private-fixture: require Green first')
        result=self.call();diagnostic=result['incident']['completion_diagnostic']
        self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(diagnostic['reads']['complete_files'],len(self.files))
        self.assertEqual(diagnostic['verdict_rejection'],'changes_require_concrete_findings')
        self.assertFalse(result['tests_approved']);self.assertFalse(result['execution_authorized'])
        self.assertNotIn('private-fixture',json.dumps(diagnostic))

    def only_new_test_reads(self):
        with self.b.db() as con:
            rows=con.execute('SELECT call_id,messages FROM observed_read_stream').fetchall()
            for identifier,raw in rows:
                if json.loads(raw)[0]['input']['path']!='/delivery/tests/test_new.py':
                    con.execute('DELETE FROM observed_read_stream WHERE call_id=?',(identifier,))

    def test_evidenced_rejection_needs_new_tests_and_citations_not_every_unrelated_file(self):
        self.only_new_test_reads()
        finding=dict(criterion='A01',path='tests/test_new.py',test='test_new',line=4,
            quote='self.assertEqual(app.VALUE, 1)',expected='Registered behavior',observed='This assertion')
        self.update_verdict(action='request_changes',findings=[finding])
        result=self.call()
        self.assertEqual(result['stage'],'changes_requested')
        self.assertEqual(result['read_scope'],'rejection_new_tests_and_citations')
        self.assertEqual(set(result['reads']),{'/delivery/tests/test_new.py'})
        self.assertFalse(result['tests_approved']);self.assertFalse(result['execution_authorized'])

    def test_partial_snapshot_can_never_approve_or_cite_an_unread_file(self):
        self.only_new_test_reads()
        self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_unread_cited_file_blocks_rejection(self):
        self.only_new_test_reads()
        finding=dict(criterion='A01',path='app.py',test='__module__',line=1,
            quote='VALUE=0',expected='Registered behavior',observed='Base code')
        self.update_verdict(action='request_changes',findings=[finding])
        self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_new_test_helper_citation_requires_real_ast_function_and_exact_line(self):
        raw=b'import unittest\nclass New(unittest.TestCase):\n def helper(self):\n  return 1\n def test_new(self): self.assertEqual(self.helper(), 1)\n'
        packet=launch_fixture.launch.review.load(self.b,self.source)[0]['packet']
        observed={'/delivery/tests/test_new.py':dict(line_content=dict(enumerate(raw.decode().splitlines(),1)))}
        value={**self.verdict,'action':'request_changes','findings':[dict(criterion='A01',path='tests/test_new.py',
            test='helper',line=4,quote='return 1',expected='Meaningful value',observed='Constant')]}
        prepared=dict(test_methods={'tests/test_new.py':['test_new']})
        self.assertEqual(attest.verdict(json.dumps(value),packet,observed,prepared)['action'],'request_changes')
        value['findings'][0]['test']='invented'
        with self.assertRaises(ValueError):attest.verdict(json.dumps(value),packet,observed,prepared)

    def test_citation_outside_the_claimed_test_method_is_not_a_valid_rejection(self):
        finding=dict(criterion='A01',path='tests/test_new.py',test='test_new',line=2,
            quote='new expectation',expected='Expected behavior',observed='Comment outside method')
        self.update_verdict(action='request_changes',findings=[finding])
        self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_citation_inside_the_actual_test_method_can_request_changes(self):
        finding=dict(criterion='A01',path='tests/test_new.py',test='test_new',line=4,
            quote='self.assertEqual(app.VALUE, 1)',expected='The registered acceptance behavior',observed='This exact assertion')
        self.update_verdict(action='request_changes',findings=[finding])
        self.assertEqual(self.call()['stage'],'changes_requested')

    def test_missing_terminal_operation_is_protocol_failure_not_success(self):
        self.f.record['result']['output']='Everything looks good; implementation may proceed.'
        result=self.call();self.assertEqual(result['stage'],'technical_blocked')

    def test_prose_before_json_diagnoses_both_format_and_missing_reads_without_reinterpretation(self):
        self.only_new_test_reads()
        self.f.record['result']['output']='I approve after inspection.\n```json\n'+json.dumps(self.verdict)+'\n```'
        result=self.call();self.assertEqual(result['stage'],'technical_blocked')
        diagnostic=result['incident']['completion_diagnostic']
        self.assertEqual(diagnostic['verdict_format'],'invalid')
        self.assertEqual(diagnostic['reads']['required_files'],4)
        self.assertEqual(diagnostic['reads']['complete_files'],1)
        self.assertEqual({r['path'] for r in diagnostic['reads']['rejected_files']},
            {'AGENTS.md','app.py','tests/test_old.py'})
        self.assertFalse(diagnostic['tests_approved']);self.assertFalse(result['tests_approved'])
        self.assertNotIn('I approve',json.dumps(diagnostic))
        self.assertEqual(self.call(),result)

    def test_valid_json_still_reports_every_missing_approval_read(self):
        self.only_new_test_reads()
        result=self.call();self.assertEqual(result['stage'],'technical_blocked')
        diagnostic=result['incident']['completion_diagnostic']
        self.assertEqual(diagnostic['verdict_format'],'valid')
        self.assertEqual(diagnostic['reads']['complete_files'],1)
        self.assertEqual(len(diagnostic['reads']['rejected_files']),3)

    def test_concrete_rejection_diagnostic_does_not_require_unrelated_approval_reads(self):
        self.only_new_test_reads()
        self.update_verdict(action='request_changes',findings=[dict(criterion='A01',path='tests/test_new.py',
            test='test_new',line=4,quote='self.assertEqual(app.VALUE, 1)',expected='An assertion',observed='This assertion')])
        with self.b.db() as con:
            messages=read_stream_receipts.load(con,self.f.record['id'])
        context=launch_fixture.launch.review.load(self.b,self.source)[0]
        files={p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in self.files.items()}
        diagnostic=attest.completion_diagnostic(self.f.record['result']['output'],context['packet'],
            files,context['read_paths'],messages)
        self.assertEqual(diagnostic['reads']['required_files'],1)
        self.assertEqual(diagnostic['reads']['complete_files'],1)
        self.assertFalse(diagnostic['tests_approved'])

    def test_incomplete_or_wrong_file_bytes_do_not_become_complete_reads(self):
        with self.b.db() as con:
            row=con.execute('SELECT messages FROM observed_read_stream LIMIT 1').fetchone()
            messages=json.loads(row[0]);messages[1]['output']=messages[1]['output'].replace('Preserve tests','Weaken tests')
            con.execute('UPDATE observed_read_stream SET messages=? WHERE call_id=?',
                (json.dumps(messages),messages[0]['call_id']))
        result=self.call();self.assertEqual(result['stage'],'technical_blocked')

    def test_unknown_native_observation_has_persistent_alert_and_cto_deadline(self):
        with patch.object(attest.time,'time',return_value=100),patch.object(attest.native,'task_record',side_effect=TimeoutError):
            with self.assertRaises(attest.validation_job.Pending):self.call()
        first=attest.status(self.b,self.source)
        self.assertFalse(first['alert_due'])
        with patch.object(attest.time,'time',return_value=701),patch.object(attest.native,'task_record',side_effect=TimeoutError):
            with self.assertRaises(attest.validation_job.Pending):self.call()
        self.assertTrue(attest.status(self.b,self.source)['alert_due'])
        with patch.object(attest.time,'time',return_value=1901),patch.object(attest.native,'task_record',side_effect=TimeoutError):
            result=self.call()
        self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['incident']['category'],'review_observation_deadline')
        self.assertEqual(result['owner'],self.b.QUALITY_CTO)
        self.assertFalse(result['tests_approved'])

    def test_sealed_operator_maintenance_does_not_capture_a_new_verdict(self):
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                ('operation','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(attest.validation_job.Pending):self.call()
        self.assertIsNone(attest.load(self.b,self.source))


if __name__=='__main__':unittest.main()
