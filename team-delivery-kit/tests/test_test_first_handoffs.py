from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from broker import handoffs, test_first_handoffs


class Broker:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()


class Effects:
    def __init__(self, broker):
        self.broker = broker
        self.calls = 0
        self.remaining = 32
        self.wakeups = []
        self.available = True

    def implementation_available(self, *_):
        return self.available

    def decision(self, _):
        if _.get('agent_id') == 'lead':
            return {'action': 'approve_test_revision', 'reason': 'Independent test inspection passed.',
                    'manifest_sha256': 'a' * 64, 'optional_files': []}
        return {'action': 'request_correction', 'reason': 'Finish the declared test and run the complete suite.',
                'optional_files': []}

    def read_evidence(self, _):
        return {'/evidence/candidate/test_static_content_type.py': {'call_id': 'observed-read'}}

    def capture_test_first_red(self, payload):
        self.calls += 1
        receipt = {'task_id': payload['task_id'],
                   'volume': 'volume',
                   'red': {'manifest_sha256': 'a' * 64,
                           'test_sha256': {'test_static_content_type.py': 'b' * 64}}}
        with self.broker.db() as con:
            con.execute('INSERT INTO test_first_red VALUES (?,?,?,?,?)',
                        ('issue', payload['task_id'], 'scope', 'volume',
                         json.dumps(receipt)))
        return receipt

    def remaining_calls(self):
        return self.remaining

    def test_first_failure(self, *_):
        return {'kind': 'rejected_red', 'exit_code': 0, 'output_excerpt': 'Ran 170 tests\nOK'}

    def ensure_wakeup(self, *_args, **_kwargs):
        self.wakeups.append((_args, _kwargs))
        return {'id': 'review-wakeup' if _args[1] == 'lead' else 'wakeup'} if _kwargs['allow_create'] else None


class TestFirstHandoffTests(unittest.TestCase):
    def test_failed_checkpoint_still_requires_independent_test_review(self):
        from unittest.mock import patch
        from broker import failed_test_checkpoint as checkpoint
        red=self.effects.capture_test_first_red({'task_id':'tests'})
        red['issue_id']='issue'
        failed={**self.test_task,'status':'failed'}
        with self.broker.db() as con:
            con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(red),))
            checkpoint.initialize(con)
            proof=dict(operation='failed_test_checkpoint_v1',status='red_captured',
                native_task_completed=False,delivery_approved=False,
                red_receipt_sha256=checkpoint.digest(red))
            con.execute('INSERT INTO failed_test_checkpoints VALUES (?,?,?)',
                        ('issue','tests',json.dumps(proof)))
        with patch('broker.test_revision_review.reconcile',return_value=False) as review:
            self.assertIsNone(test_first_handoffs.reconcile(self.broker,self.route,[failed],self.effects))
            review.assert_called_once()
        self.assertEqual(self.effects.wakeups,[])
        self.assertEqual(failed['status'],'failed')

    def test_failed_source_without_checkpoint_proof_cannot_use_red(self):
        self.effects.capture_test_first_red({'task_id':'tests'})
        failed={**self.test_task,'status':'failed'}
        with self.assertRaisesRegex(ValueError,'source identity drift'):
            test_first_handoffs.reconcile(self.broker,self.route,[failed],self.effects)

    def test_failed_typed_length_diagnosis_gets_one_nonapproving_recovery(self):
        rejection={'operation':'rejected_typed_decision_adapter_v1','category':'typed_schema_maxLength',
                   'upstream_sha256':'a'*64,'worker_tool_executed':False,'delivery_approval':False}
        self.effects.pre_red_format_rejection=lambda *_:rejection
        data={'phase':'test_first','error':'test_first_cto_execution_failed',
              'diagnostic':{'kind':'rejected_red'},'test_first_cto_wakeup':'old'}
        cto={'id':'failed-cto','agent_id':'cto','status':'failed','wakeup_id':'old'}
        with self.broker.db() as con:
            handoffs.save(con,'tests','issue','test_first_blocked','cto',data,1)
            prior=handoffs.load(con,'tests')
        test_first_handoffs.technical_recovery(self.broker,self.route,
            [self.test_task,cto],self.test_task,prior,self.effects)
        with self.broker.db() as con: state=handoffs.load(con,'tests')
        saved=json.loads(state['data'])
        self.assertEqual(state['stage'],'technical_decision_required')
        self.assertEqual(saved['decision_format_retry'],1)
        self.assertFalse(saved['previous_invalid_decision']['verdict_replayed'])
        self.assertEqual(self.effects.calls,0)
        saved.update(error='test_first_cto_execution_failed',test_first_cto_wakeup='new')
        with self.broker.db() as con:
            handoffs.save(con,'tests','issue','test_first_blocked','cto',saved,2)
            prior=handoffs.load(con,'tests')
        test_first_handoffs.technical_recovery(self.broker,self.route,
            [self.test_task,{**cto,'wakeup_id':'new'}],self.test_task,prior,self.effects)
        self.assertEqual(self.effects.wakeups,[])

    def test_other_transport_rejection_does_not_authorize_replay(self):
        self.effects.pre_red_format_rejection=lambda *_:{'category':'typed_schema_enum'}
        data={'phase':'test_first','error':'test_first_cto_execution_failed',
              'diagnostic':{'kind':'rejected_red'},'test_first_cto_wakeup':'old'}
        cto={'id':'failed-cto','agent_id':'cto','status':'failed','wakeup_id':'old'}
        with self.broker.db() as con:
            handoffs.save(con,'tests','issue','test_first_blocked','cto',data,1)
            prior=handoffs.load(con,'tests')
        test_first_handoffs.technical_recovery(self.broker,self.route,
            [self.test_task,cto],self.test_task,prior,self.effects)
        with self.broker.db() as con: state=handoffs.load(con,'tests')
        self.assertEqual(state['stage'],'test_first_blocked')
        self.assertNotIn('decision_format_retry',json.loads(state['data']))

    def test_large_diagnostic_is_preserved_but_not_serialized_into_wakeup(self):
        diagnostic={'kind':'rejected_red','reason':'unchanged new test',
                    'output_excerpt':'private traceback\n'*2000}
        data={'phase':'test_first','source_task':'tests','error':'ValueError:unchanged',
              'diagnostic':diagnostic}
        with self.broker.db() as con:
            handoffs.save(con,'tests','issue','technical_decision_required','cto',data,1)
            prior=handoffs.load(con,'tests')
        test_first_handoffs.technical_recovery(self.broker,self.route,
            [self.test_task],self.test_task,prior,self.effects)
        instruction=self.effects.wakeups[-1][0][4]
        self.assertLess(len(instruction),4000)
        self.assertNotIn('private traceback',instruction)
        self.assertIn('full_diagnostic_sha256',instruction)
        with self.broker.db() as con:
            saved=json.loads(handoffs.load(con,'tests')['data'])
        self.assertEqual(saved['diagnostic'],diagnostic)
        self.assertEqual(self.effects.calls,0)

    def test_presentation_recovery_does_not_recapture_red_or_restart_author(self):
        data={'phase':'test_first','source_task':'tests','error':'ValueError:unchanged',
              'diagnostic':{'kind':'rejected_red','output_excerpt':'x'*8000},
              'control_error':'ValueError:handoff instruction too large'}
        with self.broker.db() as con:
            handoffs.save(con,'tests','issue','diagnose_cto','cto',data,1)
        test_first_handoffs.reconcile(self.broker,self.route,[self.test_task],self.effects)
        with self.broker.db() as con:
            saved=json.loads(handoffs.load(con,'tests')['data'])
        self.assertEqual(saved['diagnostic'],data['diagnostic'])
        self.assertFalse(saved['diagnostic_presentation_recovery']['approval'])
        self.assertFalse(saved['diagnostic_presentation_recovery']['author_restarted'])
        self.assertEqual(self.effects.calls,0)
        self.assertEqual(self.effects.wakeups[-1][0][1],'cto')

    def test_oversized_structured_index_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'fixed bound'):
            test_first_handoffs.diagnostic_presentation(
                {'diagnostic':{'reason':'x'*5000}})

    def test_new_validator_evidence_reopens_only_cto_diagnosis_once(self):
        diagnostic=dict(kind='rejected_test_write',operation='rejected_test_write_v1',
            category='artifact_test_methods_missing',issue_id='issue',task_id='tests',
            write_executed=False,tests_executed=False,red_verified=False,delivery_approval=False)
        data=dict(phase='test_first',error='test_first_cto_requires_replanning',diagnostic=diagnostic,
            cto_task='old-cto',decision=dict(action='escalate_cto',optional_files=[]),test_first_cto_wakeup='old')
        with self.broker.db() as c:
            handoffs.save(c,'tests','issue','test_first_blocked','cto',data,1)
            prior=handoffs.load(c,'tests')
        test_first_handoffs.technical_recovery(self.broker,self.route,[self.test_task],self.test_task,prior,self.effects)
        with self.broker.db() as c:state=handoffs.load(c,'tests')
        self.assertEqual(state['stage'],'technical_decision_required')
        saved=json.loads(state['data']);self.assertEqual(saved['artifact_diagnosis_replay']['previous_cto_task'],'old-cto')
        self.assertNotIn('decision',saved);self.assertFalse(saved['artifact_diagnosis_replay']['author_retry_authorized'])
        test_first_handoffs.technical_recovery(self.broker,self.route,[self.test_task],self.test_task,state,self.effects)
        self.assertEqual(self.effects.wakeups[-1][0][1],'cto')
        self.assertIn('PROXY ARTIFACT REJECTION',self.effects.wakeups[-1][0][4])
        saved.update(error='test_first_cto_requires_replanning',decision=dict(action='escalate_cto',optional_files=[]))
        with self.broker.db() as c:
            handoffs.save(c,'tests','issue','test_first_blocked','cto',saved,2);prior=handoffs.load(c,'tests')
        test_first_handoffs.technical_recovery(self.broker,self.route,[self.test_task],self.test_task,prior,self.effects)
        with self.broker.db() as c:self.assertEqual(handoffs.load(c,'tests')['stage'],'test_first_blocked')

    def test_dispatched_author_is_pending_not_technical_failure(self):
        dispatched={**self.test_task,'status':'dispatched'}
        test_first_handoffs.reconcile(self.broker,self.route,[dispatched],self.effects)
        with self.broker.db() as con:
            prior=handoffs.load(con,dispatched['id'])
        self.assertEqual(prior['stage'],'test_author_active')
        self.assertNotIn('error',json.loads(prior['data']))
        self.assertEqual(self.effects.calls,0)
        self.assertEqual(self.effects.wakeups,[])

    def test_oversized_cto_decision_gets_one_changed_contract_not_author_retry(self):
        data = {'phase': 'test_first', 'error': 'test_first_cto_invalid_decision:ValueError',
                'diagnostic': {'kind': 'rejected_snapshot', 'category': 'empty_new_test'},
                'test_first_cto_wakeup': 'old-wake'}
        cto = {'id': 'old-cto', 'agent_id': 'cto', 'status': 'completed', 'wakeup_id': 'old-wake',
               'result': {'output': json.dumps({'action': 'escalate_cto',
                   'reason': 'x' * 3448, 'optional_files': []})}}
        with self.broker.db() as con:
            handoffs.save(con, 'tests', 'issue', 'test_first_blocked', 'cto', data, 1)
            prior = handoffs.load(con, 'tests')
        test_first_handoffs.technical_recovery(self.broker, self.route,
            [self.test_task, cto], self.test_task, prior, self.effects)
        with self.broker.db() as con:
            state = handoffs.load(con, 'tests')
        self.assertEqual(state['stage'], 'technical_decision_required')
        saved = json.loads(state['data'])
        self.assertEqual(saved['decision_format_retry'], 1)
        self.assertEqual(saved['previous_invalid_decision']['cto_task'], 'old-cto')
        test_first_handoffs.technical_recovery(self.broker, self.route,
            [self.test_task, cto], self.test_task, state, self.effects)
        args = self.effects.wakeups[-1][0]
        self.assertEqual(args[1], 'cto')
        self.assertIn('1200 characters', args[4])
        saved.update(error='test_first_cto_invalid_decision:ValueError')
        with self.broker.db() as con:
            handoffs.save(con, 'tests', 'issue', 'test_first_blocked', 'cto', saved, 2)
            prior = handoffs.load(con, 'tests')
        test_first_handoffs.technical_recovery(self.broker, self.route,
            [self.test_task, cto], self.test_task, prior, self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'], 'test_first_blocked')

    def test_other_invalid_decisions_do_not_trigger_format_retry(self):
        data = {'phase': 'test_first', 'error': 'test_first_cto_invalid_decision:ValueError',
                'diagnostic': {'kind': 'rejected_snapshot'}, 'test_first_cto_wakeup': 'old-wake'}
        cto = {'id': 'old-cto', 'agent_id': 'cto', 'status': 'completed', 'wakeup_id': 'old-wake',
               'result': {'output': json.dumps({'action': 'approve',
                   'reason': 'x' * 3448, 'optional_files': []})}}
        with self.broker.db() as con:
            handoffs.save(con, 'tests', 'issue', 'test_first_blocked', 'cto', data, 1)
            prior = handoffs.load(con, 'tests')
        test_first_handoffs.technical_recovery(self.broker, self.route,
            [self.test_task, cto], self.test_task, prior, self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'], 'test_first_blocked')
        self.assertEqual(self.effects.wakeups, [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.broker = Broker(Path(self.temp.name) / 'state.sqlite')
        self.broker.issue_base = lambda _: {'base_sha': 'b' * 40}
        with self.broker.db() as con:
            handoffs.initialize(con)
            con.execute('CREATE TABLE test_first_red(issue_id TEXT PRIMARY KEY, task_id TEXT, '
                        'scope TEXT, volume TEXT, receipt TEXT)')
        self.effects = Effects(self.broker)
        self.route = {'issue_id': 'issue', 'author': 'author', 'cto': 'cto',
                      'techlead': 'lead',
                      'minimum_calls': 8,
                      'test_first_files': ['test_static_content_type.py']}
        self.test_task = {'id': 'tests', 'issue_id': 'issue', 'agent_id': 'author',
                          'status': 'completed', 'created_at': '01'}

    def test_rejected_red_evidence_reaches_cto_without_granting_implementation(self):
        def reject(_):
            raise ValueError('Red must be an executed failing test suite')
        self.effects.capture_test_first_red = reject
        test_first_handoffs.reconcile(self.broker, self.route, [self.test_task], self.effects)
        with self.broker.db() as con:
            state = handoffs.load(con, 'tests')
            self.assertEqual(state['stage'], 'technical_decision_required')
            self.assertEqual(json.loads(state['data'])['diagnostic']['exit_code'], 0)
            self.assertIsNone(con.execute('SELECT 1 FROM test_first_red').fetchone())
        test_first_handoffs.reconcile(self.broker, self.route, [self.test_task], self.effects)
        args, _ = self.effects.wakeups[-1]
        self.assertEqual(args[1], 'cto')
        self.assertIn('Ran 170 tests', args[4])
        self.assertIn('rejected_red', args[4])

    def test_red_is_captured_before_implementation_handoff(self):
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task], self.effects))
        self.assertEqual(self.effects.calls, 1)
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task], self.effects))
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'], 'awaiting_test_revision_review')
        self.assertEqual(self.effects.wakeups[-1][0][1], 'lead')
        review = {'id': 'review', 'agent_id': 'lead', 'status': 'completed', 'wakeup_id': 'review-wakeup'}
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task, review], self.effects))
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'], 'awaiting_implementation')
        implementation = {'id': 'code', 'issue_id': 'issue', 'agent_id': 'author',
                          'status': 'completed', 'created_at': '02', 'wakeup_id': 'wakeup'}
        result = test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task, implementation], self.effects)
        self.assertEqual([r['id'] for r in result], ['code'])
        self.assertEqual(self.effects.calls, 1)

    def test_budget_pause_does_not_create_implementation_task(self):
        test_first_handoffs.reconcile(self.broker, self.route, [self.test_task], self.effects)
        test_first_handoffs.reconcile(self.broker, self.route, [self.test_task], self.effects)
        self.effects.remaining = 1
        review = {'id': 'review', 'agent_id': 'lead', 'status': 'completed', 'wakeup_id': 'review-wakeup'}
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task, review], self.effects))
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'], 'budget_paused')

    def test_first_idle_watchdog_gets_one_durable_tests_only_retry(self):
        failed = {**self.test_task, 'status': 'failed',
                  'failure_reason': 'idle_watchdog'}
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [failed], self.effects))
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'],
                             'awaiting_test_author_retry')
        self.assertEqual(self.effects.wakeups[0][0][1:3], ('author', 'tests'))
        self.assertIn('PHASE 1 TESTS ONLY', self.effects.wakeups[0][0][4])
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [failed], self.effects))
        second = {**failed, 'id': 'second', 'created_at': '02'}
        self.assertIsNone(test_first_handoffs.reconcile(
            self.broker, self.route, [failed, second], self.effects))
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'second')['stage'],
                             'technical_decision_required')
        self.assertEqual(len(self.effects.wakeups), 2)

    def test_idle_watchdog_retry_waits_for_budget(self):
        failed = {**self.test_task, 'status': 'failed',
                  'failure_reason': 'idle_watchdog'}
        self.effects.remaining = 1
        test_first_handoffs.reconcile(self.broker, self.route, [failed], self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'],
                             'retry_test_author_budget_paused')
        self.assertFalse(self.effects.wakeups[-1][1]['allow_create'])
        self.effects.remaining = 32
        test_first_handoffs.reconcile(self.broker, self.route, [failed], self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'],
                             'awaiting_test_author_retry')

    def test_idle_retry_waits_for_scope_release(self):
        failed = {**self.test_task, 'status': 'failed', 'failure_reason': 'idle_watchdog'}
        self.effects.available = False
        test_first_handoffs.reconcile(self.broker, self.route, [failed], self.effects)
        self.assertEqual(self.effects.wakeups, [])
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'], 'awaiting_test_author_release')
        self.effects.available = True
        test_first_handoffs.reconcile(self.broker, self.route, [failed], self.effects)
        self.assertEqual(len(self.effects.wakeups), 1)

    def test_repeated_failure_dispatches_cto_then_one_tests_only_correction(self):
        failed = {**self.test_task, 'status': 'failed', 'failure_reason': 'idle_watchdog'}
        second = {**failed, 'id': 'second', 'created_at': '02', 'failure_reason': 'initialize_failed'}
        runs = [failed, second]
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        self.assertEqual(self.effects.wakeups[-1][0][1], 'cto')
        self.assertIn('DELIVERY_STRUCTURED_DECISION_V1:technical', self.effects.wakeups[-1][0][4])
        cto = {'id': 'cto-task', 'status': 'dispatched', 'agent_id': 'cto', 'wakeup_id': 'wakeup'}
        runs.append(cto)
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con,second['id'])['stage'],'test_first_cto_diagnosis')
        self.assertEqual(len(self.effects.wakeups),1)
        cto['status']='completed'
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        self.effects.available = False
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        self.assertEqual(len(self.effects.wakeups), 1)
        self.effects.available = True
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        self.assertEqual(self.effects.wakeups[-1][0][1], 'author')
        instruction=self.effects.wakeups[-1][0][4]
        self.assertIn('unittest.TestCase',instruction)
        self.assertIn('without pytest imports',instruction)
        self.assertIn('Import/collection errors are not Red',instruction)
        third = {**second, 'id': 'third', 'created_at': '03'}
        runs.append(third)
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        test_first_handoffs.reconcile(self.broker, self.route, runs, self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'third')['stage'], 'test_first_blocked')
        self.assertEqual(len(self.effects.wakeups), 2)

    def test_one_exact_test_path_correction_after_snapshot_rejection(self):
        def reject(_):
            raise ValueError('test-first test path mismatch')
        self.effects.capture_test_first_red = reject
        test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task], self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'],
                             'technical_decision_required')
        test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task], self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'],
                             'awaiting_test_path_correction')
        self.assertIn('test_static_content_type.py',
                      self.effects.wakeups[-1][0][4])
        test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task], self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'tests')['stage'],
                             'awaiting_test_path_correction')
        corrected = {**self.test_task, 'id': 'corrected', 'created_at': '02'}
        test_first_handoffs.reconcile(
            self.broker, self.route, [self.test_task, corrected], self.effects)
        with self.broker.db() as con:
            self.assertEqual(handoffs.load(con, 'corrected')['stage'],
                             'technical_decision_required')
        self.assertEqual(len(self.effects.wakeups), 2)

    def test_generic_and_size_rejection_never_trigger_test_path_retry(self):
        for message in ('test-first snapshot rejected','test-first NEW test exceeds worker snapshot limit'):
            with self.subTest(message=message):
                with self.broker.db() as con:con.execute('DELETE FROM delivery_handoffs')
                self.effects.wakeups.clear()
                def reject(_):raise ValueError(message)
                self.effects.capture_test_first_red=reject
                test_first_handoffs.reconcile(self.broker,self.route,[self.test_task],self.effects)
                test_first_handoffs.reconcile(self.broker,self.route,[self.test_task],self.effects)
                self.assertEqual(len(self.effects.wakeups),1)
                self.assertEqual(self.effects.wakeups[0][0][1],'cto')
                with self.broker.db() as con:
                    self.assertEqual(handoffs.load(con,'tests')['stage'],'test_first_cto_diagnosis')
