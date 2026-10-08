import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from broker import handoffs
from broker.contract_revision import revised
from broker.tdd_evidence import collect
from portable_contract import validate, validate_delivery_files
from test_portable_contract import contract


class Effects:
    def __init__(self):
        self.remaining = 64
        self.created = {}
        self.lose_response = False
        self.failure = None
        self.verdict = None

    def freeze(self, task):
        if self.failure:
            raise self.failure
        return {'task_id': task, 'volume': 'frozen', 'status': 'complete'}

    def validate(self, snapshot, task):
        return {'baseline_tests_intact': True, 'manifest_sha256': 'a' * 64,
                'tests': 46, 'tdd': {'verified': True}}

    def remaining_calls(self):
        return self.remaining

    def assign(self, task, target):
        pass

    def implementation_available(self, issue, author):
        return getattr(self, 'author_available', True)

    def ensure_wakeup(self, issue, target, source, marker, instruction, *, allow_create=True):
        if marker not in self.created and not allow_create:
            return None
        self.created.setdefault(marker, {'id': 'wake-' + str(len(self.created)),
                                       'target': target, 'source': source})
        if self.lose_response:
            self.lose_response = False
            raise OSError('response lost after accepted POST')
        return self.created[marker]

    def review_result(self, task, source):
        return self.verdict

    def decision(self, recipient):
        return {'action': 'request_correction', 'reason': 'Add the required module and its tests.', 'optional_files': []}


class HandoffTests(unittest.TestCase):
    def test_validation_observation_preserves_attempts_and_never_wakes_author(self):
        from broker.validation_job import Pending
        self.effects.failure=Pending('same validation execution still running')
        self.assertEqual(self.tick([]),'validation_pending')
        first=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertEqual(first['attempts'],0)
        self.assertEqual(self.tick([]),'validation_pending')
        self.assertEqual(json.loads(handoffs.load(self.con,'source')['data'])['attempts'],0)
        self.assertFalse(self.effects.created)
    def test_extra_review_requires_registered_repair_and_fresh_cto_once(self):
        from broker import review_context_recovery as recovery
        evidence=self.effects.validate(None,None)
        data=dict(source_task='source',contract_sha256=self.route['contract_sha256'],
            snapshot=self.effects.freeze('source'),evidence=evidence,review_retries=1,
            failed_dispatch_stage='ready_review',dispatch_stage='diagnose_cto',target='cto',
            wakeup_id='wake',dispatched_at=0,review_context_recovery=dict(
                previous_blocker=dict(recipient_task='old'),request=dict(failed_review='failed')))
        recipient=dict(id='fresh-cto',issue_id='issue',agent_id='cto',status='completed',wakeup_id='wake')
        self.effects.decision=lambda _:dict(action='retry_review',reason='Changed precondition verified.',optional_files=[])
        for registered,used,expected in [(False,False,'technical_decision_required'),
                                         (True,False,'ready_review'),(True,True,'technical_decision_required')]:
            trial=dict(data)
            if used:trial['review_context_recovery_used']=dict(cto_task='previous')
            handoffs.save(self.con,'source','issue','accepted','cto',trial,1)
            with unittest.mock.patch.object(recovery,'qualified',return_value=registered):
                self.assertEqual(self.tick([recipient]),expected)
            saved=json.loads(handoffs.load(self.con,'source')['data'])
            self.assertEqual(saved['review_retries'],1)
            if expected=='ready_review':self.assertEqual(saved['review_context_recovery_used']['cto_task'],'fresh-cto')
    def test_oversized_review_diagnosis_returns_to_cto_without_approval(self):
        evidence=self.effects.validate(None,None)
        evidence['tdd']=dict(green=dict(executed_by_controller=True),red=dict(
            baseline_test_sha256={str(i):'d'*64 for i in range(100)}))
        snapshot=self.effects.freeze('source')
        recorded=dict(snapshot=snapshot,evidence=evidence,wakeup_id='oldwake',dispatch_stage='ready_review')
        handoffs.save(self.con,'source','issue','awaiting_acceptance','reviewer',recorded,1)
        error='hermes session/prompt failed: session/prompt: restricted broker stream failed: native_prompt_bounds (code=-32000)'
        data=dict(source_task='source',contract_sha256=self.route['contract_sha256'],
            snapshot=snapshot,evidence=evidence,error='recipient_execution_failed',
            control_error='ValueError:handoff instruction too large',failed_dispatch_stage='ready_review',
            recipient_error=error)
        failed=dict(id='failed-review',agent_id='reviewer',issue_id='issue',status='failed',wakeup_id='oldwake',error=error)
        for wrong in ({**failed,'wakeup_id':'stale'},{**failed,'agent_id':'author'}):
            handoffs.save(self.con,'source','issue','technical_decision_required','cto',data,2)
            self.assertEqual(self.tick([wrong]),'technical_decision_required')
        handoffs.save(self.con,'source','issue','technical_decision_required','cto',data,2)
        self.tick([failed])
        saved=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertFalse(saved['diagnosis_transport_recovery']['approval'])
        self.assertEqual(saved['dispatch_stage'],'diagnose_cto')
        self.assertNotIn('baseline_test_sha256',saved['instruction'])
        self.assertLess(len(saved['instruction']),3900)
        self.assertEqual(saved['evidence'],evidence)
        self.assertNotIn('review_retries',saved)
    def test_verified_harness_diagnosis_supersedes_pending_peer_context_not_test_review(self):
        self.route.update(test_first=True, test_first_files=['tests/new.py'])
        failure = dict(category='executed_test_failure', output_sha256='a'*64,
                       diagnostic_read_files=['app.js'])
        data = dict(source_task='source', contract_sha256=self.route['contract_sha256'],
                    dispatch_stage='diagnose_cto', target='cto', wakeup_id='wake',
                    dispatched_at=0, independent_failure_inspection={'pending': True},
                    validation_failure=failure, harness_diagnosis=dict(
                        source_task='source', output_sha256='a'*64, approval=False,
                        file_sha256={'tests/new.py':'b'*64, 'app.js':'c'*64},
                        findings=['The harness reverses request chronology.']))
        recipient=dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed',wakeup_id='wake')
        self.effects.decision=lambda _:dict(action='request_test_revision',reason='Fix the NEW harness.',optional_files=[])
        full={p:dict(lines=10,total_lines=10) for p in ['/evidence/candidate/tests/new.py','/evidence/candidate/app.js']}
        for reads,expected in [({},'technical_decision_required'),(full,'test_revision_required')]:
            with self.subTest(reads=bool(reads)):
                self.effects.read_evidence=lambda _:reads
                handoffs.save(self.con,'source','issue','accepted','cto',data,0)
                self.assertEqual(self.tick([recipient]),expected)
                saved=json.loads(handoffs.load(self.con,'source')['data'])
                if reads:
                    self.assertEqual(saved['required_action'],'independently_review_new_test_revision_then_recapture_red')
                    self.assertEqual(saved['test_revision_proposal']['decision_task'],'cto-task')
                else:
                    self.assertNotIn('test_revision_proposal',saved)
    def test_event_trace_context_deduplicates_runs_without_dropping_events(self):
        report=dict(total_events=2,truncated=False,events=[dict(sequence=1,kind='context_created',context=1),dict(sequence=2,kind='fetch_started',context=1,method='GET',query=None)])
        proof=dict(operation='frozen_js_event_order_experiment_v1',approval=False,untraced_observations_equal=True,output_sha256='a'*64,event_reports=[report,report])
        receipt=dict(approval=False,proof=proof);failure=dict(output_sha256='a'*64)
        summary=handoffs.event_order_summary(receipt,failure)
        self.assertEqual(summary['run_trace_indices'],[0,0]);self.assertEqual(len(summary['traces'][0]['rows']),2)
        with self.assertRaises(ValueError):handoffs.event_order_summary({**receipt,'approval':True},failure)
        with self.assertRaises(ValueError):handoffs.event_order_summary(receipt,dict(output_sha256='b'*64))
    def test_independent_contract_reserves_transport_prefix_and_full_proposal(self):
        route={**self.route,'test_first_files':['tests/new.py']}
        data=dict(source_task='source',validation_failure=dict(category='executed_test_failure',output_sha256='a'*64,
            diagnostic_read_files=['app.js'],failures=[dict(qualified_name='tests.new.Case.test_x')]),
            independent_failure_finding=dict(decision=dict(reason='x'*1200)))
        note=handoffs.independent_failure_instruction(data,route,'diagnose_cto')
        self.assertLess(len('DELIVERY_HANDOFF '+'a'*64+'\n'+note),4000)
        self.assertIn('x'*1200,note);self.assertIn('/evidence/candidate/tests/new.py',note)
        bad={**data,'runtime_assertion_experiment':dict(approval=True,proof=dict(runtime_observations=[]))}
        with self.assertRaises(ValueError):handoffs.independent_failure_instruction(bad,route,'diagnose_cto')
    def test_independent_inspection_requires_full_candidate_and_test_reads(self):
        route={**self.route,'test_first_files':['tests/new.py']};data=dict(validation_failure=dict(diagnostic_read_files=['app.js']))
        reads={p:dict(lines=10,total_lines=10) for p in ('/evidence/candidate/tests/new.py','/evidence/candidate/app.js')}
        self.assertEqual(len(handoffs.independent_inspection_reads(route,data,reads)),2)
        for bad in ({}, {**reads,'/evidence/candidate/app.js':dict(lines=5,total_lines=10)}):
            with self.assertRaises(ValueError):handoffs.independent_inspection_reads(route,data,bad)
    def test_repeated_failure_requires_independent_diagnosis_before_cto(self):
        failure=dict(category='executed_test_failure',source_task='new',output_sha256='a'*64,failures=[dict(qualified_name='tests.new.Case.test_x')])
        old={**failure,'source_task':'old','output_sha256':'b'*64}
        row=dict(source_task='new',issue_id='issue',stage='budget_paused',data=json.dumps(dict(contract_sha256=self.route['contract_sha256'],artifact_diagnosis=True,validation_failure=failure,resume_stage='diagnose_cto')))
        prior=dict(source_task='old',issue_id='issue',data=json.dumps(dict(contract_sha256=self.route['contract_sha256'],validation_failure=old)))
        data=handoffs.prepare_independent_failure_inspection(row,prior,self.route)
        self.assertEqual(data['resume_stage'],'diagnose');self.assertFalse(data['independent_failure_inspection']['delivery_approval'])
        with self.assertRaises(ValueError):handoffs.prepare_independent_failure_inspection({**row,'data':json.dumps(data)},prior,self.route)
        with self.assertRaises(ValueError):handoffs.prepare_independent_failure_inspection(row,{**prior,'data':json.dumps(dict(validation_failure={**old,'failures':[]}))},self.route)

    def test_lost_candidate_correction_needs_independent_qualification(self):
        data=dict(source_task='source',contract_sha256=self.route['contract_sha256'],
                  dispatch_stage='diagnose_cto',target='cto',recipient_task='cto-task',
                  wakeup_id='wake',dispatched_at=0,lost_execution_diagnostic=dict(volume='diag',
                    preservation=dict(inspection=dict(manifest_sha256='a'*64))),
                  diagnostic_revision='lost-v1',artifact_diagnosis=True,
                  validation_failure=dict(category='executed_test_failure',diagnostic_read_files=['app.js']))
        self.effects.read_evidence=lambda recipient: {'/evidence/candidate/app.js':{'observed':True}}
        handoffs.save(self.con,'source','issue','accepted','cto',data,0)
        cto=dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed',wakeup_id='wake')
        self.assertEqual(self.tick([cto]),'diagnose')
        current=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertEqual(current['lost_correction_qualification']['cto_task'],'cto-task')
        self.assertFalse(self.effects.created)
        self.tick([cto],now=110)
        current=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertEqual(current['target'],'lead')
        lead=dict(id='lead-task',agent_id='lead',issue_id='issue',status='completed',wakeup_id=current['wakeup_id'])
        self.assertEqual(self.tick([cto,lead],now=120),'correct_author')
        current=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertEqual(current['lost_correction_approval']['techlead_task'],'lead-task')
        self.assertFalse(current['lost_correction_approval']['delivery_approval'])
        self.assertFalse(current['lost_correction_approval']['tests_may_change'])

    def test_oversized_artifact_diagnosis_requires_bound_rejection_and_never_replays_verdict(self):
        route=dict(cto='cto',issue_id='issue')
        task=dict(id='failed',agent_id='cto',issue_id='issue',status='failed',wakeup_id='wake')
        data=dict(recipient_task='failed',wakeup_id='wake',failed_dispatch_stage='diagnose_cto',
                  artifact_diagnosis=True,validation_failure=dict(category='executed_test_failure'),
                  instruction='DELIVERY_TYPED_DECISION_V1',diagnostic_revision='artifact')
        row=dict(stage='technical_decision_required',owner='cto',issue_id='issue',data=json.dumps(data))
        proof=dict(operation='rejected_typed_decision_adapter_v1',category='typed_schema_maxLength',
                   execution_id='execution',upstream_sha256='a'*64)
        fixed=handoffs.prepare_concise_diagnosis_retry(row,task,route,proof)
        self.assertEqual(fixed['concise_diagnosis_retry']['previous_blocker'],data)
        self.assertFalse(fixed['concise_diagnosis_retry']['verdict_replayed'])
        self.assertNotIn('recipient_task',fixed)
        self.assertNotIn('decision',fixed)
        with self.assertRaises(ValueError):
            handoffs.prepare_concise_diagnosis_retry({**row,'data':json.dumps(fixed)},task,route,proof)
        for changed in ({**proof,'category':'typed_schema_enum'},{**proof,'upstream_sha256':''}):
            with self.assertRaises(ValueError):handoffs.prepare_concise_diagnosis_retry(row,task,route,changed)
        with self.assertRaises(ValueError):
            handoffs.prepare_concise_diagnosis_retry(row,{**task,'wakeup_id':'unrelated'},route,proof)

    def test_padding_artifact_retry_requires_proven_shape_and_is_one_time(self):
        route=dict(cto='cto',issue_id='issue')
        task=dict(id='failed',agent_id='cto',issue_id='issue',status='failed',wakeup_id='wake')
        data=dict(recipient_task='failed',wakeup_id='wake',failed_dispatch_stage='diagnose_cto',
                  artifact_diagnosis=True,validation_failure=dict(category='executed_test_failure'),
                  instruction='DELIVERY_TYPED_DECISION_V1')
        row=dict(stage='technical_decision_required',owner='cto',issue_id='issue',data=json.dumps(data))
        shape=dict(parsed=True,terminal=True,expected_tool=True,arguments_json_valid=True,
                   arguments_schema_valid=True,content_shape='whitespace_only',content_chars=2,
                   submissions=1,legacy_function_call=False)
        proof=dict(operation='rejected_typed_decision_adapter_v1',category='typed_mixed_content',
                   execution_id='request',upstream_sha256='a'*64,response_shape=shape)
        fixed=handoffs.prepare_padding_diagnosis_retry(row,task,route,proof)
        self.assertEqual(fixed['validation_failure'],data['validation_failure'])
        self.assertNotIn('wakeup_id',fixed);self.assertFalse(fixed['padding_diagnosis_retry']['verdict_replayed'])
        for changes in (dict(content_shape='non_whitespace'),dict(content_chars=17),
                        dict(arguments_schema_valid=False),dict(terminal=False),dict(submissions=2)):
            with self.assertRaises(ValueError):
                handoffs.prepare_padding_diagnosis_retry(row,task,route,{**proof,'response_shape':{**shape,**changes}})
        with self.assertRaises(ValueError):
            handoffs.prepare_padding_diagnosis_retry(row,{**task,'id':'other'},route,proof)
        with self.assertRaises(ValueError):
            handoffs.prepare_padding_diagnosis_retry({**row,'data':json.dumps(fixed)},task,route,proof)

    def test_concise_retry_survives_artifact_instruction_replacement(self):
        data = dict(source_task='source', contract_sha256=self.route['contract_sha256'],
                    error='recipient_execution_failed', artifact_diagnosis=True,
                    concise_diagnosis_retry=dict(verdict_replayed=False),
                    validation_failure=dict(category='executed_test_failure'))
        handoffs.save(self.con, 'source', 'issue', 'diagnose_cto', 'cto', data, 0)
        self.tick(now=1)
        current = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertIn('DELIVERY_TYPED_DECISION_V1', current['instruction'])
        self.assertIn('target <=300 characters', current['instruction'])

    def test_compact_trial_requires_real_qualified_prompt_and_is_single_use(self):
        import hashlib
        task=dict(id='failed',agent_id='cto',issue_id='issue',status='failed',wakeup_id='wake')
        route=dict(cto='cto',issue_id='issue')
        data=dict(recipient_task='failed',wakeup_id='wake',instruction='Exact real instruction',unchanged_diagnosis_retry=dict(attempted=True))
        row=dict(stage='technical_decision_required',owner='cto',data=json.dumps(data))
        proof=dict(operation='isolated_typed_envelope_qualification_v1',payload='authorized_real_diagnosis',context='compact',
                   status='finished',http_status=200,instruction_sha256=hashlib.sha256(data['instruction'].encode()).hexdigest())
        adapter=dict(operation='validated_typed_decision_adapter_v1',worker_tool_executed=False,delivery_approval=False)
        fixed=handoffs.prepare_compact_diagnosis_trial(row,task,route,proof,adapter)
        self.assertIn('compact_diagnosis_trial',fixed);self.assertNotIn('wakeup_id',fixed)
        for bad in ({**proof,'payload':'wholly_synthetic'},{**proof,'instruction_sha256':'bad'}):
            with self.assertRaises(ValueError):handoffs.prepare_compact_diagnosis_trial(row,task,route,bad,adapter)
        data['compact_diagnosis_trial']={'attempted':True}
        with self.assertRaises(ValueError):handoffs.prepare_compact_diagnosis_trial({**row,'data':json.dumps(data)},task,route,proof,adapter)

    def test_unchanged_correction_diagnosis_does_not_copy_unbounded_suite_logs(self):
        incident=dict(category='unchanged_rejected_delivery',previous_source='previous',source_task='source',
            review_task='review',manifest_sha256='a'*64,finding='Clarify the disputed client behavior')
        data=dict(evidence=dict(tests=249,output='sensitive transcript '*10000,correction_diagnosis=incident))
        instruction=handoffs.unchanged_correction_instruction(data)
        self.assertLess(len('DELIVERY_HANDOFF '+'b'*64+'\n'+instruction),4000)
        self.assertIn(incident['finding'],instruction)
        self.assertIn('controller_green_evidence_sha256',instruction)
        self.assertNotIn('sensitive transcript',instruction)
        self.assertIn('DELIVERY_TYPED_DECISION_V1',instruction)
        self.assertIn('submit_delivery_decision',instruction)
        self.assertNotIn('Do not call tools.',instruction)
        self.assertIn('Do not approve',instruction)
        incident['finding']='x'*601
        with self.assertRaises(ValueError):handoffs.unchanged_correction_instruction(data)

    def test_unchanged_diagnosis_transport_repair_is_exact_and_single(self):
        task=dict(id='failed',agent_id='cto',issue_id='issue',status='failed',wakeup_id='wake')
        route=dict(cto='cto',issue_id='issue')
        data=dict(recipient_task='failed',wakeup_id='wake',failed_dispatch_stage='diagnose_cto',
            evidence=dict(correction_diagnosis=dict(category='unchanged_rejected_delivery')),
            instruction='DELIVERY_TYPED_DECISION_V1\nDo not call tools.')
        row=dict(stage='technical_decision_required',owner='cto',data=json.dumps(data))
        rejection=dict(operation='rejected_typed_decision_adapter_v1',category='typed_mixed_content',
                       execution_id='execution',upstream_sha256='a'*64)
        fixed=handoffs.prepare_unchanged_diagnosis_retry(row,task,route,rejection)
        self.assertNotIn('wakeup_id',fixed);self.assertIn('unchanged_diagnosis_retry',fixed)
        self.assertFalse(fixed['unchanged_diagnosis_retry']['delivery_approval'])
        for changed in ({**task,'id':'other'},{**task,'status':'completed'}):
            with self.assertRaises(ValueError):handoffs.prepare_unchanged_diagnosis_retry(row,changed,route,rejection)
        data['unchanged_diagnosis_retry']={};data['unchanged_diagnosis_retry']['attempted']=True
        with self.assertRaises(ValueError):handoffs.prepare_unchanged_diagnosis_retry({**row,'data':json.dumps(data)},task,route,rejection)

    def test_capture_constraint_diagnosis_is_bounded_and_automatic(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        receipt = evidence(1, 'FAIL: test_capture (tests.test_capture.Cases.test_capture)\n'
            'AssertionError: bad\nRan 10 tests\nFAILED (failures=1)', 'source', 'frozen')
        self.route.update(test_first=True, test_first_files=['tests/test_capture.py'])
        self.effects.failure = FrozenSuiteFailure(receipt)
        self.effects.capture_report = lambda issue: {'witnesses': [{
            'path': 'tests/test_capture.py', 'capture': 'oldest',
            'whole': {'line': 10, 'expected': [1, 2, 10]},
            'element': {'line': 20, 'index': -1, 'expected': 11}, 'implied_element': 10}]}
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertIn('DELIVERY_CAPTURE_CONSTRAINTS_V1', data['instruction'])
        self.assertEqual(data['capture_constraints'][0]['implied_element'], 10)
        self.assertLess(len('DELIVERY_HANDOFF ' + 'a'*64 + '\n' + data['instruction']), 4000)
        self.effects.validate_capture_decision = lambda *args: (_ for _ in ()).throw(
            ValueError('product correction cannot resolve contradiction'))
        self.assertEqual(self.tick([self.recipient(target='lead')]), 'diagnose_cto')
        self.assertNotEqual(handoffs.load(self.con, 'source')['stage'], 'correct_author')
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(data['capture_format_retry'], 1)
        self.assertIn('cannot resolve', data['capture_protocol_failure']['reason'])
        self.tick(now=110)
        self.assertEqual(self.tick([self.recipient(target='cto')], now=120),
                         'technical_decision_required')
        self.assertFalse(any(w['target'] == 'author' for w in self.effects.created.values()))

    def test_all_seven_failure_names_reach_diagnosis_without_duplicate_fields(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        self.route.update(test_first=True, test_first_files=['tests/test_filter.py'])
        output = '\n'.join('FAIL: test_case_' + str(n) + ' (tests.test_filter.Guards.test_case_' + str(n) + ')'
                           for n in range(7)) + '\nRan 190 tests\nFAILED (failures=7)'
        self.effects.failure = FrozenSuiteFailure(evidence(1, output, 'source', 'frozen'))
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        for n in range(7):
            self.assertIn('tests.test_filter.Guards.test_case_' + str(n), data['instruction'])
        self.assertIn('"failure_count":7', data['instruction'])
        self.assertIn('new_frozen_test', data['instruction'])
        self.assertLess(len('DELIVERY_HANDOFF ' + 'a' * 64 + '\n' + data['instruction']), 4000)

    def test_inherited_red_failure_uses_lossless_context_without_local_red(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        from broker.bound_failure_context import expand
        self.effects.test_first_red=lambda task:dict(issue_id='r1',task_id='test-author')
        output='\n'.join('FAIL: test_case_'+str(n)+' (tests.test_new.Cases.test_case_'+str(n)+')'
                         for n in range(30))+'\nRan 323 tests\nFAILED (failures=30)'
        self.effects.failure=FrozenSuiteFailure(evidence(1,output,'source','frozen'))
        self.tick()
        row=handoffs.load(self.con,'source');data=json.loads(row['data'])
        self.assertTrue(data['artifact_diagnosis'])
        self.assertLess(len('DELIVERY_HANDOFF '+'a'*64+'\n'+data['instruction']),4000)
        full=expand(data['instruction'],'issue',dict(agent_id=data['target'],wakeup_id=data['wakeup_id']),
                    lambda source:row)
        for n in range(30):self.assertIn('tests.test_new.Cases.test_case_'+str(n),full)
        self.assertNotIn('approve',str(data.get('decision','')))

    def test_correction_budget_is_issue_scoped_not_reset_for_each_author_task(self):
        data = {'contract_sha256': self.route['contract_sha256'], 'error': 'artifact_validation: new code and test files required',
                'dispatch_stage': 'correct_author'}
        for number in (1, 2):
            prior = dict(data, dispatch_marker='marker-' + str(number))
            for _ in range(2):
                handoffs.save(self.con, 'old-' + str(number), 'issue', 'dispatch_intent', 'author', prior, 90)
        self.assertEqual(handoffs.repeated_corrections(self.con, 'issue', data), 2)
        self.assertEqual(handoffs.repeated_corrections(self.con, 'issue', dict(data, error='executed_test_failure')), 0)
        handoffs.save(self.con, 'source', 'issue', 'correct_author', 'author', data, 100)
        self.tick()
        state = handoffs.load(self.con, 'source')
        self.assertEqual(state['stage'], 'technical_decision_required')
        self.assertFalse(self.effects.created)

    def test_diagnosis_receives_existing_red_instead_of_inventing_missing_tests(self):
        self.effects.phase_evidence = lambda _: {'phase': 'implementation', 'red_manifest': 'a' * 64,
                                                'independent_test_review': 'approved'}
        self.effects.failure = ValueError('new product code required; new test files present=1')
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(data['phase_evidence']['independent_test_review'], 'approved')
        self.assertIn('red_manifest', data['instruction'])

    def test_structural_diagnosis_requires_actual_candidate_reads_before_correction(self):
        proof=dict(candidate_manifest_sha256='a'*64,product_read_files=['app.js'],new_test_files=['tests/test_new.py'])
        data=dict(source_task='source',contract_sha256=self.route['contract_sha256'],
            error='missing product delta',attempts=1,structural_diagnosis=proof)
        handoffs.save(self.con,'source','issue','diagnose_cto','cto',data,0)
        self.tick(now=1)
        stored=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertIn('Green suite was NOT executed',stored['instruction'])
        self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/app.js',stored['instruction'])
        self.effects.verdict=dict(action='request_correction',reason='Implement query state',optional_files=[])
        self.effects.read_evidence=lambda _:['/evidence/candidate/app.js']
        recipient=self.recipient(target='cto');self.tick([recipient],now=2)
        self.assertEqual(handoffs.load(self.con,'source')['stage'],'technical_decision_required')

    def test_context_exhaustion_is_not_diagnosed_as_missing_artifacts(self):
        from unittest.mock import patch
        self.author['result'] = {'output': 'Context length exceeded (125,854 tokens). Cannot compress further.'}
        with patch.object(self.effects, 'freeze', side_effect=AssertionError('must not freeze exhausted run')) as freeze:
            self.tick()
        freeze.assert_not_called()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertIn('author_context_exhausted', data['error'])
        self.assertIn('Cannot compress further', data['source_execution_error'])
        self.assertIn('preserve accepted Red', data['instruction'])

    def test_frozen_failure_names_the_new_test_file_and_mounts_diagnosis_automatically(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        self.route.update(test_first=True, test_first_files=['tests/test_pending.py'])
        self.effects.failure = FrozenSuiteFailure(evidence(1,
            'FAIL: test_render (tests.test_pending.Guard.test_render)\n'
            'AssertionError: private\nRan 124 tests\nFAILED (failures=1)', 'source', 'frozen'))
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertTrue(data['artifact_diagnosis'])
        self.assertIn('DELIVERY_STRUCTURED_DECISION_V1:technical\n', data['instruction'])
        self.assertIn('DELIVERY_TYPED_DECISION_V1\n', data['instruction'])
        self.assertIn('tests.test_pending.Guard.test_render', data['instruction'])
        self.assertIn('new_frozen_test', data['instruction'])
        self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/tests/test_pending.py', data['instruction'])
        self.assertLessEqual(len(data['instruction']), 3800)

    def test_invalid_cto_format_has_one_independent_bounded_retry(self):
        data = {'source_task': 'source', 'contract_sha256': self.route['contract_sha256'],
                'artifact_diagnosis': True, 'diagnostic_revision': 'evidence-v1',
                'recipient_task': 'invalid-cto', 'control_error': 'ValueError:invalid technical decision',
                'control_error_count': 2, 'attempts': 1}
        handoffs.save(self.con, 'source', self.route['issue_id'], 'technical_decision_required', 'cto', data, 100)
        task = {'issue_id': self.route['issue_id'], 'agent_id': 'cto',
                'id': 'invalid-cto', 'status': 'completed', 'created_at': '02'}
        self.tick([task], now=110)
        state = handoffs.load(self.con, 'source')
        data = json.loads(state['data'])
        self.assertEqual(data['diagnostic_format_retries'], 1)
        self.assertEqual(data['invalid_decision_task'], 'invalid-cto')
        self.assertIn('optional_files MUST be []', data['instruction'])
        self.assertFalse(any(w['target'] == 'author' for w in self.effects.created.values()))
        data.update(control_error='ValueError:invalid technical decision', control_error_count=2)
        handoffs.save(self.con, 'source', self.route['issue_id'], 'technical_decision_required', 'cto', data, 120)
        self.assertEqual(self.tick([task], now=130), 'technical_decision_required')
        self.assertEqual(len(self.effects.created), 1)

    def test_typed_artifact_recovery_is_exact_failed_cto_and_one_time(self):
        data={'recipient_task':'failed-cto','wakeup_id':'wake','error':'recipient_execution_failed',
              'artifact_diagnosis':True,'instruction':'Old diagnosis',
              'diagnostic_revision':'sha:artifacts-v1',
              'validation_failure':{'category':'executed_test_failure'}}
        row={'stage':'technical_decision_required','issue_id':'issue','owner':'cto','data':json.dumps(data)}
        task={'id':'failed-cto','issue_id':'issue','agent_id':'cto','status':'failed','wakeup_id':'wake'}
        proof={'task_id':'failed-cto','execution_id':'bound-request','status':502,
               'category':'structured_decision_response_invalid'}
        result=handoffs.prepare_typed_artifact_recovery(row,task,self.route,proof)
        self.assertEqual(result['validation_failure'],data['validation_failure'])
        self.assertFalse(result['typed_artifact_recovery']['delivery_approval'])
        self.assertNotIn('wakeup_id',result)
        for invalid in ({**task,'status':'completed'},{**task,'agent_id':'author'},
                        {**task,'wakeup_id':'another'}):
            with self.assertRaises(ValueError):
                handoffs.prepare_typed_artifact_recovery(row,invalid,self.route,proof)
        with self.assertRaises(ValueError):
            handoffs.prepare_typed_artifact_recovery(row,task,self.route,{**proof,'status':200})
        with self.assertRaises(ValueError):
            handoffs.prepare_typed_artifact_recovery({**row,'data':json.dumps({**data,
                'typed_artifact_recovery':result['typed_artifact_recovery']})},task,self.route,proof)

    def test_new_test_revision_requires_cto_and_never_grants_author_write(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        self.route.update(test_first=True, test_first_files=['tests/test_new.py'])
        self.effects.failure = FrozenSuiteFailure(evidence(
            1, 'FAIL: test_new (tests.test_new.New.test_new)\nRan 114 tests\nFAILED (failures=1)',
            'source', 'frozen'))
        self.effects.decision = lambda _: {'action': 'request_test_revision',
                                          'reason': 'Incorrect mock DOM and count invariant.',
                                          'optional_files': []}
        self.tick()
        lead = self.recipient(target='lead')
        self.assertEqual(self.tick([lead]), 'diagnose_cto')
        self.tick([lead], now=110)
        cto = {**self.recipient(target='cto'), 'id': 'cto-decision'}
        self.assertEqual(self.tick([lead, cto], now=120), 'test_revision_required')
        state = handoffs.load(self.con, 'source')
        self.assertEqual(state['owner'], 'reviewer')
        data = json.loads(state['data'])
        self.assertEqual(data['test_revision_proposal']['decision_task'], 'cto-decision')
        self.assertFalse(any(w['target'] == 'author' for w in self.effects.created.values()))
        self.assertEqual(self.tick([lead, cto], now=130), 'test_revision_required')
        self.assertEqual(len(self.effects.created), 2)

    def test_diagnosis_receives_actual_structured_green_failure(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        receipt = evidence(1, 'FAIL: test_new (tests.test_new.New.test_new)\n'
                           'AssertionError: private\nRan 114 tests\nFAILED (failures=1)',
                           'source', 'frozen')
        self.effects.failure = FrozenSuiteFailure(receipt)
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(data['validation_failure'], receipt)
        self.assertIn('executed_test_failure', data['instruction'])
        self.assertIn('completed author task is NOT evidence of Green', data['instruction'])
        self.assertNotIn('AssertionError: private', data['instruction'])

    def test_artifact_diagnosis_fits_native_wakeup_with_realistic_failures(self):
        from broker.suite_failure import evidence, FrozenSuiteFailure
        receipt = evidence(1, 'FAIL: test_new (tests.test_new.New.test_new)\n'
                           'AssertionError: private\nRan 114 tests\nFAILED (failures=1)',
                           'source', 'frozen')
        receipt['failures'] = [{'kind': 'FAIL', 'test': 'test_summary_counts_refresh_after_creation_and_completion',
            'qualified_name': 'tests.test_browser_feedback_flow.BrowserFeedbackFlowTests.' + 'x' * 150} for _ in range(5)]
        receipt['numeric_assertion_details'] = [{'expected': {'completed': '1', 'open': '2', 'total': '2'},
                                                'observed': {'completed': 1, 'open': 1, 'total': 2}}]
        self.effects.failure = FrozenSuiteFailure(receipt)
        self.tick()
        row = handoffs.load(self.con, 'source')
        data = json.loads(row['data'])
        data['artifact_diagnosis'] = True
        handoffs.save(self.con, 'source', self.route['issue_id'], 'diagnose_cto', 'cto', data, 105)
        self.tick(now=110)
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertLess(len('DELIVERY_HANDOFF ' + 'a' * 64 + '\n' + data['instruction']), 4000)
        self.assertEqual(data['validation_failure'], receipt)
        self.assertIn('/evidence/candidate', data['instruction'])

    def test_failed_execution_diagnosis_counts_envelope_and_preserves_all_failures(self):
        self.test_artifact_diagnosis_fits_native_wakeup_with_realistic_failures()
        data=json.loads(handoffs.load(self.con,'source')['data'])
        failure=data['validation_failure']
        data.update(source_status='failed',source_failure_reason='agent_error.provider_server_error',
            failed_execution_diagnostic=dict(status='diagnostic_only_not_approved'),
            phase_evidence=dict(phase='implementation',red_exit_code=1,red_manifest='c'*64,
                independent_test_review='approved',frozen_test_hashes={'tests/test_new.py':'d'*64}),
            diagnostic_revision='failed-snapshot-v1')
        self.route['test_first_files']=['tests/test_new.py']
        for key in ('wakeup_id','recipient_task','dispatch_marker','dispatch_stage','instruction','target'):
            data.pop(key,None)
        handoffs.save(self.con,'source',self.route['issue_id'],'diagnose_cto','cto',data,120)
        self.tick(now=121)
        current=json.loads(handoffs.load(self.con,'source')['data'])
        note='DELIVERY_HANDOFF '+'a'*64+'\n'+current['instruction']
        self.assertLessEqual(len(note),4000)
        self.assertEqual(current['validation_failure'],failure)
        for item in failure['failures']:self.assertIn(item['qualified_name'],note)
        self.assertIn('unchanged Red hashes',note)
        self.assertIn('never authority',note)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.con = self.connect()
        self.addCleanup(lambda: self.con.close())
        handoffs.initialize(self.con)
        self.route = {'issue_id': 'issue', 'author': 'author', 'reviewer': 'reviewer',
                      'techlead': 'lead', 'cto': 'cto', 'enabled': True,
                      'minimum_calls': 8, 'contract_sha256': 'b' * 64,
                      'review_instruction': 'Review the frozen delivery.'}
        self.author = {'id': 'source', 'issue_id': 'issue', 'agent_id': 'author',
                       'status': 'completed', 'created_at': '01', 'result': {'output': 'Done'}}
        self.effects = Effects()

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def tick(self, extra=(), now=100):
        return handoffs.reconcile(self.con, self.route, [self.author, *extra], self.effects, now=now)

    def recipient(self, status='completed', target='reviewer'):
        state = json.loads(handoffs.load(self.con, 'source')['data'])
        return {'id': 'recipient', 'issue_id': 'issue', 'agent_id': target,
                'status': status, 'created_at': '02', 'wakeup_id': state['wakeup_id']}

    def test_review_context_binds_full_receipt_without_duplicated_test_inventory(self):
        receipt = dict(mode='controller_test_first', red=dict(exit_code=1,
            manifest_sha256='a'*64, output_sha256='c'*64, test_count=265,
            baseline_test_sha256={f'tests/test_{n}.py':'d'*64 for n in range(100)}),
            green=dict(manifest_sha256='e'*64, tests=265, executed_by_controller=True))
        evidence = dict(tdd=receipt, manifest_sha256='e'*64, baseline_tests_intact=True)
        self.effects.validate = lambda *_: evidence
        self.route['review_instruction'] = 'R'*2500
        self.tick()
        data = json.loads(handoffs.load(self.con,'source')['data'])
        self.assertLessEqual(len('DELIVERY_HANDOFF '+'a'*64+'\n'+data['instruction']),4000)
        context=handoffs.review_tdd_context(evidence)
        self.assertEqual(context['red']['test_count'],265)
        self.assertEqual(context['green']['manifest_sha256'],'e'*64)
        self.assertEqual(len(context['receipt_sha256']),64)
        self.assertNotIn('baseline_test_sha256',context['red'])
        self.assertEqual(data['evidence']['tdd'],receipt)

    def test_oversized_predispatch_review_recovers_same_snapshot_once(self):
        evidence=self.effects.validate(None,None)
        data=dict(contract_sha256=self.route['contract_sha256'],snapshot=dict(
            task_id='source',volume='frozen',status='complete'),evidence=evidence)
        handoffs.save(self.con,'source','issue','ready_review','reviewer',data,80)
        data.update(control_error='ValueError:handoff instruction too large',control_error_count=3)
        handoffs.save(self.con,'source','issue','technical_decision_required','cto',data,90)
        self.assertEqual(self.tick(),'awaiting_acceptance')
        recovered=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertFalse(recovered['review_transport_recovery']['approval'])
        self.assertEqual(recovered['snapshot'],data['snapshot'])
        self.tick(now=110)
        self.assertEqual(len(self.effects.created),1)
        self.assertEqual(next(iter(self.effects.created.values()))['target'],'reviewer')

    def test_transport_recovery_rejects_drift_and_unproven_or_dispatched_failure(self):
        for variant in ('no_ready','already_dispatched','functional_failure','drift'):
            with self.subTest(variant=variant):
                self.con.execute('DELETE FROM delivery_handoff_events')
                self.con.execute('DELETE FROM delivery_handoffs')
                data=dict(contract_sha256=self.route['contract_sha256'],snapshot=dict(
                    task_id='source',volume='frozen'),evidence=dict(
                    baseline_tests_intact=True,manifest_sha256='a'*64,tests=46,tdd={}))
                if variant!='no_ready':
                    handoffs.save(self.con,'source','issue','ready_review','reviewer',data,80)
                data.update(control_error='ValueError:handoff instruction too large')
                if variant=='already_dispatched':data['wakeup_id']='existing'
                if variant=='functional_failure':data['validation_failure']={'category':'executed_test_failure'}
                handoffs.save(self.con,'source','issue','technical_decision_required','cto',data,90)
                if variant=='drift':
                    self.effects.validate=lambda *_:dict(baseline_tests_intact=True,manifest_sha256='b'*64,tests=46)
                    with self.assertRaisesRegex(ValueError,'snapshot drift'):self.tick()
                else:self.assertEqual(self.tick(),'technical_decision_required')
                self.assertFalse(self.effects.created)

    def test_restart_after_remote_acceptance_does_not_duplicate_wakeup(self):
        self.effects.lose_response = True
        with self.assertRaises(OSError):
            self.tick()
        self.con.close()
        self.con = self.connect()
        self.assertEqual(self.tick(now=110), 'awaiting_acceptance')
        self.assertEqual(len(self.effects.created), 1)
        self.effects.verdict = {'status': 'approved', 'manifest_sha256': 'a' * 64}
        self.assertEqual(self.tick([self.recipient()], now=120), 'approved')
        self.assertEqual(self.tick([self.recipient()], now=130), 'approved')

    def test_budget_pause_resumes_exact_same_handoff(self):
        self.effects.remaining = 1
        self.assertEqual(self.tick(), 'budget_paused')
        self.assertFalse(self.effects.created)
        self.effects.remaining = 32
        self.assertEqual(self.tick(now=200), 'awaiting_acceptance')
        self.assertEqual(len(self.effects.created), 1)

    def test_broker_503_retries_author_once_then_escalates_as_infrastructure(self):
        self.author.update(status='failed', error='hermes session/prompt failed: '
                           'restricted broker operation failed: http_503 (code=-32000)',
                           result=None)
        older = {**self.author, 'id': 'old-failure', 'created_at': '00'}
        intervening = {**self.author, 'id': 'old-success', 'created_at': '00a',
                       'status': 'completed', 'error': None, 'result': {'output': 'Done'}}
        self.assertEqual(self.tick([older, intervening]), 'awaiting_acceptance')
        first = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(first['source_failure_kind'], 'broker_http_503')
        self.assertIn('do not infer a code defect', first['finding'])
        later = {**self.author, 'id': 'source2', 'created_at': '02'}
        self.assertEqual(self.tick([older, intervening, later], now=200), 'awaiting_acceptance')
        second = json.loads(handoffs.load(self.con, 'source2')['data'])
        self.assertEqual(second['dispatch_stage'], 'diagnose')
        self.assertEqual(second['error_type'], 'infrastructure')
        self.assertEqual(len(self.effects.created), 2)

    def test_lost_response_is_reconciled_even_after_budget_exhaustion(self):
        self.effects.lose_response = True
        with self.assertRaises(OSError):
            self.tick()
        self.effects.remaining = 0
        self.assertEqual(self.tick(now=110), 'awaiting_acceptance')
        self.effects.verdict = {'status': 'approved', 'manifest_sha256': 'a'*64}
        self.assertEqual(self.tick([self.recipient()], now=120), 'approved')
        self.assertEqual(len(self.effects.created), 1)

    def test_invalid_snapshot_goes_to_techlead_not_reviewer(self):
        self.effects.failure = ValueError('required artifact missing: app/store.py')
        self.assertEqual(self.tick(), 'awaiting_acceptance')
        self.assertEqual(next(iter(self.effects.created.values()))['target'], 'lead')
        self.assertEqual(self.tick([self.recipient(target='lead')]), 'correct_author')
        self.tick([self.recipient(target='lead')], now=110)
        self.assertEqual(len(self.effects.created), 2)
        self.assertEqual(list(self.effects.created.values())[-1]['target'], 'author')

    def test_failed_candidate_correction_requires_independent_evidence_not_cto_prose(self):
        self.author['status'] = 'failed'
        data = {'target': 'cto', 'dispatch_stage': 'diagnose_cto', 'wakeup_id': 'wake',
                'contract_sha256': self.route['contract_sha256'],
                'dispatched_at': 100, 'failed_execution_diagnostic': {'status': 'diagnostic_only_not_approved'},
                'validation_failure': {'category': 'executed_test_failure'}}
        handoffs.save(self.con, 'source', 'issue', 'accepted', 'cto', data, 100)
        recipient = self.recipient(target='cto')
        self.assertEqual(self.tick([recipient], now=110), 'technical_decision_required')
        state = handoffs.load(self.con, 'source')
        self.assertEqual(state['owner'], 'lead')
        data = json.loads(state['data'])
        self.assertEqual(data['required_action'], 'independently_validate_candidate_correction')
        self.assertEqual(data['diagnostic_correction_proposal']['task'], recipient['id'])
        self.assertFalse(self.effects.created)

    def test_third_identical_tdd_failure_stops_without_another_wakeup(self):
        self.effects.failure = ValueError('tdd_evidence_missing: exact executed Red then Green required')
        previous = []
        for index in range(3):
            self.author = {**self.author, 'id': 'source' + str(index),
                           'created_at': str(index + 1).zfill(2)}
            stage = self.tick(previous, now=100 + index)
            previous.append(dict(self.author))
        self.assertEqual(stage, 'technical_decision_required')
        row = handoffs.load(self.con, 'source2')
        self.assertEqual(row['owner'], 'cto')
        self.assertEqual(json.loads(row['data'])['required_action'],
                         'repair_test_first_protocol_before_retry')
        self.assertEqual(len(self.effects.created), 2)
        self.assertEqual(self.tick(previous, now=200), 'technical_decision_required')
        self.assertEqual(len(self.effects.created), 2)

    def test_change_request_targets_original_author(self):
        self.tick()
        self.effects.verdict = {'status': 'changes_requested', 'finding': 'Add boundary coverage.'}
        recipient = self.recipient()
        self.assertEqual(self.tick([recipient]), 'correct_author')
        self.tick([recipient], now=110)
        self.assertEqual(list(self.effects.created.values())[-1]['target'], 'author')
        self.assertEqual(list(self.effects.created.values())[-1]['source'], 'recipient')

    def test_author_correction_waits_for_release_before_wakeup(self):
        self.tick()
        self.effects.verdict = {'status': 'changes_requested', 'finding': 'Finish initial refresh.'}
        recipient = self.recipient()
        self.assertEqual(self.tick([recipient]), 'correct_author')
        self.effects.author_available = False
        self.assertEqual(self.tick([recipient], now=110), 'correct_author')
        self.assertEqual(len(self.effects.created), 1)
        self.effects.author_available = True
        self.assertEqual(self.tick([recipient], now=120), 'awaiting_acceptance')
        self.assertEqual(list(self.effects.created.values())[-1]['target'], 'author')

    def test_failed_execution_preserves_actual_error_for_diagnosis(self):
        self.author.update(status='failed', result=None,
                           failure_reason='idle_watchdog', error='No messages for 3 minutes')
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(data['source_failure_reason'], 'idle_watchdog')
        self.assertEqual(data['source_execution_error'], 'No messages for 3 minutes')

    def test_failed_review_retries_same_snapshot_once_without_author_dispatch(self):
        self.tick()
        failed = self.recipient(status='failed')
        failed['error'] = 'prompt_timeout'
        self.assertEqual(self.tick([failed]), 'diagnose')
        self.tick([failed], now=110)
        diagnosis = self.recipient(target='lead')
        self.effects.decision = lambda _: {'action': 'retry_review',
                                           'reason': 'Retry failed reviewer on the unchanged snapshot.',
                                           'optional_files': []}
        self.assertEqual(self.tick([failed, diagnosis], now=120), 'ready_review')
        self.tick([failed, diagnosis], now=130)
        self.assertEqual([x['target'] for x in self.effects.created.values()],
                         ['reviewer', 'lead', 'reviewer'])
        state = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(state['snapshot']['volume'], 'frozen')
        self.assertEqual(state['evidence']['manifest_sha256'], 'a' * 64)
        retry_failed = self.recipient(status='failed')
        self.assertEqual(self.tick([retry_failed], now=140), 'diagnose')
        self.tick([retry_failed], now=150)
        self.assertEqual(self.tick([self.recipient(target='lead')], now=160),
                         'technical_decision_required')

    def test_review_retry_cannot_override_author_artifact_failure(self):
        self.effects.failure = ValueError('required artifact missing')
        self.tick()
        self.effects.decision = lambda _: {'action': 'retry_review',
                                           'reason': 'Retry without fixing the artifact.',
                                           'optional_files': []}
        with self.assertRaisesRegex(ValueError, 'review retry requires'):
            self.tick([self.recipient(target='lead')])

    def test_stale_approval_never_advances(self):
        self.tick()
        self.effects.verdict = {'status': 'approved', 'manifest_sha256': 'c' * 64}
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.tick([self.recipient()])
        self.assertNotEqual(handoffs.load(self.con, 'source')['stage'], 'approved')

    def test_author_retry_requires_registered_runtime_repair_and_cto(self):
        self.author.update(status='failed', failure_reason='idle_watchdog', error='idle stall')
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        data['execution_repair'] = {'request': {'source_task': 'source', 'worker_image': 'sha256:'+'d'*64},
                                    'api_max_retries': 1}
        for field in ('recipient_task', 'wakeup_id', 'dispatch_marker', 'dispatched_at', 'instruction'):
            data.pop(field, None)
        handoffs.save(self.con, 'source', 'issue', 'diagnose_cto', 'cto', data, 110)
        self.tick(now=120)
        current = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertIn('api_max_retries=1', current['instruction'])
        from decision_schema import apply
        wire = apply({'messages': [{'role': 'user', 'content': current['instruction']}]})
        self.assertEqual(wire['response_format']['json_schema']['schema']['properties']['action']['enum'],
                         ['retry_author', 'escalate_cto'])
        self.effects.decision = lambda _: {'action': 'retry_author', 'reason': 'Changed runtime prevents internal retries.', 'optional_files': []}
        self.assertEqual(self.tick([self.recipient(target='cto')], now=130), 'correct_author')
        current = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertTrue(current['execution_repair_used'])
        self.assertNotIn('evidence', current)

    def test_author_retry_without_runtime_evidence_is_rejected(self):
        self.author.update(status='failed', failure_reason='idle_watchdog', error='idle stall')
        self.tick()
        self.effects.decision = lambda _: {'action': 'retry_author', 'reason': 'Try again.', 'optional_files': []}
        with self.assertRaisesRegex(ValueError, 'unused controller runtime repair'):
            self.tick([self.recipient(target='lead')])

    def test_pretool_interruption_retry_requires_durable_qualification_and_cto(self):
        self.author.update(status='failed', failure_reason='agent_error.process_failure', error='process exited')
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        proof = dict(request=dict(issue_id='issue',source_task='source'), stage='qualified_cto_decision',
                     worker_image='sha256:'+'a'*64,probe_request='probe',
                     probe_status='passed', author_retry_authorized=False, delivery_approval=False,
                     phase_evidence=None, fault=dict(signal='SIGKILL',accepted_tools_before=0),
                     proof=dict(frozen_tests_unchanged=True))
        data['worker_interruption_recovery'] = proof
        for field in ('recipient_task','wakeup_id','dispatch_marker','dispatched_at','instruction'):
            data.pop(field,None)
        self.con.execute('CREATE TABLE worker_interruption_recoveries(issue_id TEXT PRIMARY KEY,receipt TEXT)')
        self.con.execute('INSERT INTO worker_interruption_recoveries VALUES (?,?)', ('issue',json.dumps(proof)))
        handoffs.save(self.con,'source','issue','diagnose_cto','cto',data,110)
        self.tick(now=120)
        current=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertIn('DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1',current['instruction'])
        self.assertIn('Never recreate Red',current['instruction'])
        from decision_schema import apply
        wire=apply(dict(messages=[dict(role='user',content=current['instruction'])]))
        self.assertEqual(wire['response_format']['json_schema']['schema']['properties']['action']['enum'],
                         ['retry_author','escalate_cto'])
        self.effects.decision=lambda _:dict(action='retry_author',reason='Healthy probe; interrupted before tools.',optional_files=[])
        self.assertEqual(self.tick([self.recipient(target='cto')],now=130),'correct_author')
        current=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertTrue(current['worker_interruption_recovery_used'])
        handoffs.save(self.con,'source','issue','accepted','cto',current,140)
        with self.assertRaises(ValueError):self.tick([self.recipient(target='cto')],now=150)

    def test_restored_budget_contract_resumes_only_unissued_cto_repair(self):
        self.author.update(status='failed', failure_reason='idle_watchdog', error='idle stall')
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        data.update(execution_repair={'request': {'worker_image': 'sha256:'+'a'*64}},
                    control_error='ValueError:invalid budget status')
        for field in ('recipient_task', 'wakeup_id', 'dispatch_marker', 'dispatched_at', 'instruction'):
            data.pop(field, None)
        handoffs.save(self.con, 'source', 'issue', 'technical_decision_required', 'cto', data, 110)
        self.assertEqual(self.tick(now=120), 'awaiting_acceptance')
        current = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertTrue(current['budget_contract_recovered'])
        self.assertEqual(current['target'], 'cto')
        self.assertNotIn('control_error', current)

    def test_runtime_repair_reformats_completed_cto_once_without_parsing_prose(self):
        self.author.update(status='failed', failure_reason='idle_watchdog', error='idle stall')
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        data.update(execution_repair={'request': {'worker_image': 'sha256:'+'a'*64}},
                    diagnostic_revision='repair', recipient_task='bad-cto',
                    control_error='JSONDecodeError:Expecting value')
        handoffs.save(self.con, 'source', 'issue', 'technical_decision_required', 'cto', data, 110)
        recipient = {'id':'bad-cto', 'status':'completed', 'agent_id':'cto', 'issue_id':'issue'}
        self.assertEqual(self.tick([recipient], now=120), 'awaiting_acceptance')
        current = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertTrue(current['execution_repair_format_retry'])
        self.assertIn('DELIVERY_STRUCTURED_DECISION_V1:technical', current['instruction'])
        current['control_error'] = 'JSONDecodeError:Expecting value'
        current['recipient_task'] = 'bad-cto'
        handoffs.save(self.con, 'source', 'issue', 'technical_decision_required', 'cto', current, 130)
        self.assertEqual(self.tick([recipient], now=140), 'technical_decision_required')

    def test_failed_author_diagnosis_keeps_typed_contract_when_escalating_to_cto(self):
        self.author.update(status='failed', failure_reason='agent_error.process_failure',
                           error='hermes initialize failed: hermes process exited')
        self.tick()
        failed = self.recipient(status='failed', target='lead')
        self.assertEqual(self.tick([failed], now=110), 'diagnose_cto')
        self.tick([failed], now=120)
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertIn('DELIVERY_EXECUTION_DIAGNOSIS_V1', data['instruction'])
        self.assertIn('DELIVERY_TYPED_DECISION_V1', data['instruction'])
        from decision_schema import apply
        from typed_decision_contract import apply as typed
        wire = typed(apply({'messages': [{'role': 'user', 'content': data['instruction']}]}))
        self.assertEqual(wire['tool_choice']['function']['name'], 'submit_delivery_decision')
        self.assertEqual(wire['tools'][0]['function']['parameters']['properties']['action']['enum'],
                         ['escalate_cto'])
        self.assertFalse(any(w['target'] == 'author' for w in self.effects.created.values()))

    def test_failed_author_keeps_red_evidence_and_formats_diagnosis_once(self):
        self.author.update(status='failed', failure_reason='idle_watchdog', error='idle stall')
        self.effects.phase_evidence = lambda _: {'phase':'implementation', 'red_exit_code':1,
                                                'red_manifest':'a'*64}
        self.tick()
        data = json.loads(handoffs.load(self.con, 'source')['data'])
        self.assertEqual(data['phase_evidence']['red_exit_code'], 1)
        data.update(control_error='JSONDecodeError:Expecting value', recipient_task='bad-cto')
        handoffs.save(self.con, 'source', 'issue', 'technical_decision_required', 'cto', data, 110)
        recipient = {'id':'bad-cto','agent_id':'cto','status':'completed','issue_id':'issue'}
        self.assertEqual(self.tick([recipient], now=120), 'awaiting_acceptance')
        current = json.loads(handoffs.load(self.con, 'source')['data'])
        from decision_schema import apply
        wire = apply({'messages':[{'role':'user','content':current['instruction']}]})
        self.assertEqual(wire['response_format']['json_schema']['schema']['properties']['action']['enum'], ['escalate_cto'])
        self.assertTrue(current['execution_diagnosis_format_retry'])
        self.assertFalse(any(w['target']=='author' for w in self.effects.created.values()))

    def test_missing_acceptance_alerts_then_escalates(self):
        self.tick()
        self.tick(now=701)
        self.assertTrue(json.loads(handoffs.load(self.con, 'source')['data'])['alerted'])
        self.assertEqual(self.tick(now=1901), 'diagnose')

    def test_pause_prevents_every_effect(self):
        self.route['enabled'] = False
        self.assertEqual(self.tick(), 'paused')
        self.assertFalse(self.effects.created)

    def test_dispatched_review_is_accepted_without_terminal_verdict(self):
        self.tick()
        recipient=self.recipient(status='dispatched')
        self.assertEqual(self.tick([recipient],now=110),'accepted')
        data=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertNotIn('recipient_error',data)
        self.assertEqual(len(self.effects.created),1)

    def test_active_author_completion_and_corrected_revision_each_get_handoff(self):
        self.author['status'] = 'dispatched'
        self.assertEqual(self.tick(), 'author_active')
        self.assertFalse(self.effects.created)
        self.author['status'] = 'running'
        self.assertEqual(self.tick(), 'author_active')
        self.author['status'] = 'completed'
        self.assertEqual(self.tick(now=110), 'awaiting_acceptance')
        self.effects.verdict = {'status': 'changes_requested', 'finding': 'Add boundary test.'}
        reviewer = self.recipient()
        self.tick([reviewer], now=120)
        self.tick([reviewer], now=130)
        old = dict(self.author)
        self.author = {**self.author, 'id': 'source2', 'created_at': '03'}
        self.assertEqual(self.tick([old, reviewer], now=140), 'awaiting_acceptance')
        self.assertEqual(handoffs.load(self.con, 'source')['stage'], 'superseded')
        data = json.loads(handoffs.load(self.con, 'source2')['data'])
        final_review = {**reviewer, 'id': 'review2', 'wakeup_id': data['wakeup_id'], 'created_at': '04'}
        self.effects.verdict = {'status': 'approved', 'manifest_sha256': 'a'*64}
        self.assertEqual(self.tick([old, reviewer, final_review], now=150), 'approved')
        self.assertEqual(len(self.effects.created), 3)


class ContractRevisionTests(unittest.TestCase):
    def test_only_new_non_test_code_can_be_optional(self):
        spec = contract()
        spec['files'].append('optional.py')
        spec['editable_files'].append('optional.py')
        baseline = ['AGENTS.md', 'app.py', 'tests/test_old.py']
        new = revised(spec, baseline, ['optional.py'])
        self.assertEqual(new['schema_version'], 2)
        self.assertNotIn('optional.py', new['required_files'])
        validate_delivery_files(new, set(new['files']) - {'optional.py'}, baseline)
        for name in ('app.py', 'AGENTS.md', 'tests/test_new.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                revised(spec, baseline, [name])
        with self.assertRaises(ValueError):
            validate_delivery_files(new, set(new['files']) - {'tests/test_old.py'}, baseline)

    def test_schema_rejects_optional_tests(self):
        spec = contract()
        spec.update(schema_version=2, required_files=['AGENTS.md', 'app.py'])
        with self.assertRaises(ValueError):
            validate(spec)


class TddTests(unittest.TestCase):
    def messages(self, command):
        result = []
        for index, output in enumerate(('ERROR: test_new\n- **exit_code:** 1',
                                        'Ran 46 tests in 0.5s\nOK\n- **exit_code:** 0')):
            result.extend([
                {'task_id': 'author', 'call_id': str(index), 'seq': index*2,
                 'type': 'tool_use', 'tool': 'terminal', 'input': {'text': '$ ' + command}},
                {'task_id': 'author', 'call_id': str(index), 'seq': index*2+1,
                 'type': 'tool_result', 'tool': 'terminal', 'output': output}])
        return result

    def test_real_ordered_tool_receipts_required(self):
        result = collect(self.messages('test-command'), 'test-command')
        self.assertEqual(result['red']['exit_code'], 1)
        with self.assertRaises(ValueError):
            collect(self.messages('test-command; echo 0'), 'test-command')
        with self.assertRaises(ValueError):
            collect([{'type': 'text', 'content': 'Red and Green passed'}], 'test-command')
