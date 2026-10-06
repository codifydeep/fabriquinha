from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import patch

from broker import handoffs, test_revision_review as revision


class RevisionReviewTests(unittest.TestCase):
    def test_candidate_gate_cannot_accept_false_approval_or_stale_snapshot(self):
        import hashlib
        scope = [{'file': 'test_new.py', 'test': 'Tests.test_case', 'title': 'Σίσυφος task'}]
        red = {'red': {'manifest_sha256': 'a' * 64}}
        fact = {**scope[0], 'query': 'σισυφος', 'query_line': 218, 'casefold_substring': False}
        receipt = {'manifest_sha256': 'a' * 64,
            'scope_sha256': hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
            'operation': 'python_str_strip_casefold_substring_v1', 'fixture_literals_only': True,
            'facts': [fact], 'contradictions': [{**fact, 'asserted_match': True}]}
        with self.assertRaisesRegex(ValueError, 'contradict'):
            revision.validate_candidate_semantics(receipt, red, scope)
        receipt['contradictions'] = []
        revision.validate_candidate_semantics(receipt, red, scope)
        with self.assertRaisesRegex(ValueError, 'identity'):
            revision.validate_candidate_semantics({**receipt, 'manifest_sha256': 'b' * 64}, red, scope)
        with self.assertRaises(ValueError):
            revision.validate_candidate_semantics({k: v for k, v in receipt.items() if k != 'contradictions'}, red, scope)
    def test_semantic_review_basis_excludes_contradictory_sponsor_prose(self):
        from broker.candidate_qualification import experiment_hash
        fact = {'file': 'test_new.py', 'query_line': 218, 'query': 'σισυφος',
                'title': 'Σίσυφος task', 'casefold_substring': False}
        proof = {'facts': [fact], 'manifest_sha256': 'a' * 64, 'output_sha256': 'b' * 64}
        ack = {'experiment_sha256': experiment_hash(proof), 'semantic_checks': [
            {'fact_index': 0, 'casefold_substring': False}]}
        config = {'cto_decision': 'decision', 'reason': 'Wrong claim that accentless Greek matches',
                  'old_red': {'red': {'test_sha256': {'test_new.py': 'c' * 64}}}}
        data = {'semantic_fixture_experiment': proof, 'candidate_qualification': {
            'stage': 'semantic_test_revision_qualified', 'sponsor_task': 'decision',
            'review_decision': ack, 'sponsor_decision': ack},
            'semantic_repair_findings': {'experiment_sha256': experiment_hash(proof),
                'manifest_sha256': 'a' * 64, 'output_sha256': 'b' * 64,
                'status': 'findings_only_not_approval',
                'contradictions': [{**fact, 'asserted_match': True}]}}
        reason = revision.review_reason(config, data)
        self.assertNotIn('Wrong claim', reason)
        self.assertIn('218', reason)
        self.assertIn('accent-preserving', reason)
        self.assertEqual(config['reason'], 'Wrong claim that accentless Greek matches')
        data['semantic_repair_findings']['experiment_sha256'] = 'd' * 64
        with self.assertRaises(ValueError):
            revision.review_reason(config, data)

    def test_large_comparison_keeps_bounded_index_and_full_evidence(self):
        methods = ['Cases.test_' + str(i) + '_long_name' * 10 for i in range(100)]
        state = {'comparison': {'files': {'tests/test_new.py': {
            'previous_methods': [], 'candidate_methods': methods,
            'previous_assertions': 0, 'candidate_assertions': 200,
            'removed_methods': [], 'added_methods': methods,
            'removed_assertion_ast': []}}}}
        before = json.dumps(state, sort_keys=True)
        instruction = revision.evidence_instruction(state)
        encoded = instruction.split('approval): ', 1)[1].split('\n', 1)[0]
        summary = json.loads(encoded)
        self.assertLessEqual(len(encoded), 1200)
        self.assertTrue(summary['summary_only'])
        self.assertEqual(summary['method_counts'], [0, 100])
        self.assertEqual(summary['added_method_count'], 100)
        self.assertEqual(json.dumps(state, sort_keys=True), before)

    def pagination_fixture(self):
        self.broker.LOCK = threading.RLock()
        self.broker.STATE = Path(self.temp.name)
        (self.broker.STATE / 'native.json').write_text('{}')
        state = {'status': 'blocked', 'source_task': 'new-tests', 'candidate_volume': 'candidate',
                 'wakeup_id': 'wake', 'manifest_sha256': 'a' * 64,
                 'reason': 'invalid_independent_test_review:ValueError'}
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET state=?', (json.dumps(state),))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('child', json.dumps({'enabled': False})))
            con.execute('CREATE TABLE leases(status TEXT)')
            con.execute('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)')
            con.execute('INSERT INTO test_first_red VALUES (?,?)', ('child', json.dumps(self.red)))
        task = {'id': 'loop', 'status': 'completed', 'agent_id': 'lead', 'wakeup_id': 'wake',
                'result': {'output': 'Context length exceeded (51,489 tokens). Cannot compress further.'}}
        messages = [{'type': 'tool_result', 'output':
                     'Read failed: BLOCKED: You have called read_file on this exact region 10 times'}]
        return {'issue_id': 'child', 'failed_task': 'loop', 'manifest_sha256': 'a' * 64}, task, messages

    def test_pagination_repair_preserves_red_and_failure_and_is_idempotent(self):
        payload, task, messages = self.pagination_fixture()
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=messages):
            first = revision.resume_pagination(self.broker, payload)
            self.assertEqual(revision.resume_pagination(self.broker, payload), first)
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
            self.assertEqual(json.loads(con.execute('SELECT receipt FROM test_first_red').fetchone()[0]), self.red)
        self.assertEqual(state['pagination_retry'], 1)
        self.assertEqual(state['pagination_failed_task'], 'loop')
        self.assertEqual(state['pagination_incident']['terminal_output'], task['result']['output'])
        self.assertNotIn('wakeup_id', state)
        with self.assertRaisesRegex(ValueError, 'snapshot identity drift'):
            revision.resume_pagination(self.broker, {**payload, 'manifest_sha256': 'b' * 64})

    def test_storage_repair_preserves_red_without_promoting_old_approval(self):
        payload, task, _ = self.pagination_fixture()
        with self.db() as con:
            con.execute('UPDATE delivery_routes SET config=?',
                        (json.dumps({'enabled': False, 'test_first_files': ['test_feature.py']}),))
        task['result']['output'] = '{"action":"approve_test_revision"}'
        messages = [{'type': 'tool_result', 'tool': 'read_file',
                     'output_truncated': True, 'output': 'cut'}]
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=messages):
            result = revision.resume_pagination(self.broker, payload, storage_repair=True)
            self.assertEqual(revision.resume_pagination(self.broker, payload, storage_repair=True), result)
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
            self.assertEqual(json.loads(con.execute('SELECT receipt FROM test_first_red').fetchone()[0]), self.red)
        self.assertEqual(state['storage_retry'], 1)
        self.assertEqual(state['status'], 'dispatch_intent')
        self.assertNotIn('review_task', state)
        self.assertNotIn('read_evidence', state)
        self.assertEqual(state['storage_incident']['terminal_output'], task['result']['output'])

    def test_storage_repair_requires_recorded_truncation(self):
        payload, task, _ = self.pagination_fixture()
        with self.db() as con:
            con.execute('UPDATE delivery_routes SET config=?',
                        (json.dumps({'enabled': False, 'test_first_files': ['test_feature.py']}),))
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'recorded truncation'):
                revision.resume_pagination(self.broker, payload, storage_repair=True)

    def test_pagination_repair_cannot_override_verdict_or_missing_incident(self):
        payload, task, messages = self.pagination_fixture()
        with patch('broker.native.issue_task_runs', return_value=[{**task, 'result': {'output':
                json.dumps({'action': 'reject_test_revision', 'reason': 'Observed regression'})}}]):
            with self.assertRaisesRegex(ValueError, 'cannot be overridden'):
                revision.resume_pagination(self.broker, payload)
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'read-loop evidence'):
                revision.resume_pagination(self.broker, payload)

    def test_pagination_repair_requires_idle_route_and_exact_frozen_red(self):
        payload, task, messages = self.pagination_fixture()
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            revision.resume_pagination(self.broker, payload)
        with self.db() as con:
            con.execute('DELETE FROM leases')
            con.execute('UPDATE test_first_red SET receipt=?', (json.dumps({**self.red, 'volume': 'other'}),))
        with self.assertRaisesRegex(ValueError, 'frozen Red identity drift'):
            revision.resume_pagination(self.broker, payload)

    def test_acp_repair_is_separate_bounded_and_requires_actual_guard_failure(self):
        payload, task, messages = self.pagination_fixture()
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
            state.update(pagination_retry=1, pagination_failed_task='previous-loop')
            con.execute('UPDATE test_revision_trials SET state=?', (json.dumps(state),))
        task['result']['output'] = 'HTTP 400: {"error":{"code":"review_inspection_stalled"}}'
        messages = [{'type': 'tool_result', 'output': json.dumps({'status': 'unchanged',
                     'dedup': True, 'content_returned': False})}]
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=messages):
            result = revision.resume_pagination(self.broker, payload, acp_repair=True)
            self.assertEqual(revision.resume_pagination(self.broker, payload, acp_repair=True), result)
        with self.db() as con:
            saved = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(saved['pagination_failed_task'], 'previous-loop')
        self.assertEqual(saved['acp_retry'], 1)
        self.assertEqual(saved['acp_failed_task'], 'loop')

    def test_unread_decision_retry_is_bounded_and_preserves_previous_decision(self):
        self.broker.LOCK = threading.RLock()
        self.broker.STATE = Path(self.temp.name)
        (self.broker.STATE / 'native.json').write_text('{}')
        state = {'status': 'blocked', 'source_task': 'new-tests', 'wakeup_id': 'wake',
                 'manifest_sha256': 'a' * 64, 'review_task': 'unread', 'reason': 'No evidence observed'}
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET state=?', (json.dumps(state),))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('child', json.dumps({'enabled': False})))
            con.execute('CREATE TABLE leases(status TEXT)')
        payload = {'issue_id': 'child', 'review_task': 'unread', 'manifest_sha256': 'a' * 64}
        task = {'id': 'unread', 'status': 'completed', 'agent_id': 'lead', 'wakeup_id': 'wake'}
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=[{'type': 'tool_use', 'tool': 'read_file'}]):
            with self.assertRaisesRegex(ValueError, 'cannot be overridden'):
                revision.resume_inspection(self.broker, payload)
        with patch('broker.native.issue_task_runs', return_value=[task]), \
                patch('broker.native.task_messages', return_value=[{'type': 'text', 'content': 'I read it'}]):
            self.assertEqual(revision.resume_inspection(self.broker, payload), {'resumed': True})
            self.assertEqual(revision.resume_inspection(self.broker, payload), {'resumed': True})
        with self.db() as con:
            saved = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(saved['uninspected_reason'], 'No evidence observed')
        self.assertEqual(saved['inspection_retry'], 1)

    def test_decision_without_observed_reads_cannot_approve_or_reject(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.effects.read_evidence = lambda _: {}
        self.assertFalse(revision.reconcile(self.broker, self.route, [self.reviewer()], self.effects, self.red))
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'], 'blocked')
        self.assertNotIn('review_task', state)

    def test_evidence_policy_uses_fixed_comparison_and_rejects_invalid_finding(self):
        summary = {'files': {'tests/test_new.py': {'previous_methods': ['Cases.test_keep'],
            'candidate_methods': ['Cases.test_keep'], 'previous_assertions': 1,
            'candidate_assertions': 1, 'removed_methods': [], 'added_methods': [], 'removed_assertion_ast': {}}}}
        self.effects.test_review_report = lambda *args: summary
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertIn('DELIVERY_TYPED_REVIEW_V1:'+'a'*64, self.last_instruction)
        with patch('broker.test_revision_review.validate_evidence', side_effect=ValueError('invented test')):
            self.assertFalse(revision.reconcile(self.broker, self.route, [self.reviewer('reject_test_revision')], self.effects, self.red))
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['evidence_policy'], 1)
        self.assertEqual(state['comparison'], summary)
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['review_failure']['detail'], 'invented test')
        self.assertNotIn('review_task', state)

    def test_previous_approval_with_clipped_lines_is_preserved_but_cannot_advance(self):
        state = {'status': 'approved', 'source_task': 'new-tests', 'manifest_sha256': 'a'*64,
                 'review_task': 'independent-review', 'read_evidence': {'claimed': 'full'},
                 'decision': {'action': 'approve_test_revision'}, 'evidence_policy': 1}
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET state=?', (json.dumps(state),))
        self.effects.read_evidence = lambda _: {}
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        with self.db() as con:
            saved = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(saved['status'], 'blocked')
        self.assertEqual(saved['read_invalidation']['decision'], state['decision'])
        self.assertEqual(saved['reason'], 'approved_review_has_incomplete_source_lines')
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))


    def test_bootstrap_retry_preserves_manifest_and_is_idempotent(self):
        self.broker.LOCK = threading.RLock()
        self.broker.STATE = Path(self.temp.name)
        (self.broker.STATE / 'native.json').write_text('{}')
        state = {'status': 'blocked', 'source_task': 'new-tests', 'wakeup_id': 'wake',
                 'manifest_sha256': 'a' * 64}
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET state=?', (json.dumps(state),))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('child', json.dumps({'enabled': False})))
            con.execute('CREATE TABLE leases(status TEXT)')
            con.execute('ALTER TABLE native_bindings ADD COLUMN task_id TEXT')
            con.execute("UPDATE native_bindings SET task_id='failed'")
            con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            con.execute("INSERT INTO broker_errors VALUES ('request','transport_start','bootstrap:broker_internal',0)")
        payload = {'issue_id': 'child', 'failed_task': 'failed', 'manifest_sha256': 'a' * 64}
        task = {'id': 'failed', 'status': 'failed', 'agent_id': 'lead', 'wakeup_id': 'wake'}
        with patch('broker.native.issue_task_runs', return_value=[task]):
            first = revision.resume_bootstrap(self.broker, payload)
            self.assertEqual(revision.resume_bootstrap(self.broker, payload), first)
        with self.db() as con:
            saved = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(saved['manifest_sha256'], 'a' * 64)
        self.assertEqual(saved['bootstrap_retry'], 1)
        self.assertNotIn('wakeup_id', saved)
        with self.assertRaisesRegex(ValueError, 'identity drift'):
            revision.resume_bootstrap(self.broker, {**payload, 'manifest_sha256': 'b' * 64})
    def registration_fixture(self):
        parent = '01a0f44d-fc5d-75be-8a8f-ab806b0d49c2'
        child = '01a0f53a-deeb-7c6c-bb3a-625795812f6d'
        route = {'cto': 'cto', 'author': 'author', 'techlead': 'lead',
                 'test_first': True, 'test_first_files': ['tests/test_new.py'],
                 'contract_sha256': 'a' * 64}
        self.broker.LOCK = threading.RLock()
        self.broker.issue_base = lambda _: {'base_sha': 'b' * 40}
        with self.db() as con:
            con.execute('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)')
            con.execute('DELETE FROM test_revision_trials')
            for issue in (parent, child):
                con.execute('INSERT INTO delivery_routes VALUES (?,?)', (issue, json.dumps(route)))
            con.execute('INSERT INTO test_first_red VALUES (?,?)', (parent, json.dumps(
                {'task_id': 'old-tests', 'volume': 'historic',
                 'red': {'test_sha256': {'tests/test_new.py': 'd' * 64}}})))
            handoffs.save(con, 'failed-source', parent, 'test_revision_required', 'reviewer', {
                'target': 'cto', 'test_revision_proposal': {'decision_task': 'cto-decision',
                'reason': 'Incorrect NEW mock.', 'new_test_files': ['tests/test_new.py']}}, 100)
        return {'issue_id': child, 'parent_issue': parent}

    def test_registration_is_idempotent_and_keeps_original_red(self):
        payload = self.registration_fixture()
        first = revision.register(self.broker, payload)
        self.assertEqual(revision.register(self.broker, payload), first)
        with self.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM test_first_red').fetchone()[0], 1)
        self.assertEqual(first['old_red']['volume'], 'historic')

    def test_registration_rejects_unsponsored_or_different_base(self):
        payload = self.registration_fixture()
        self.broker.issue_base = lambda i: {'base_sha': ('b' if i == payload['parent_issue'] else 'c') * 40}
        with self.assertRaisesRegex(ValueError, 'original Git base'):
            revision.register(self.broker, payload)
        with self.db() as con:
            con.execute("UPDATE delivery_handoffs SET stage='technical_decision_required'")
        with self.assertRaisesRegex(ValueError, 'CTO-sponsored'):
            revision.register(self.broker, payload)

    def controls_registration_fixture(self):
        payload=self.registration_fixture()
        experiment={'input_sha256':{'tests/test_new.py':'e'*64}}
        proof={'operation':'immutable_candidate_missing_controls_diagnosis_v1',
            'task_id':'old-tests','manifest_sha256':'f'*64,'test_sha256':{'tests/test_new.py':'d'*64}}
        with self.db() as con:
            historic=json.loads(con.execute('SELECT receipt FROM test_first_red').fetchone()[0])
            historic['red']['manifest_sha256']='f'*64
            con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(historic),))
            parent={'harness_selector_experiment':experiment,'harness_fixture_volume':'owned-fixture'}
            con.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',
                (payload['parent_issue'],None,json.dumps(parent),'{}'))
            data=json.loads(con.execute('SELECT data FROM delivery_handoffs').fetchone()[0])
            data.update(parent,controls_completion=proof)
            con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(data),))
        return payload,experiment,proof

    def test_controls_revision_keeps_original_experiment_and_current_red_separate(self):
        payload,experiment,proof=self.controls_registration_fixture()
        with patch('broker.incremental_harness_replan.validate_experiment') as validate:
            config=revision.register(self.broker,payload)
        validate.assert_called_once_with(experiment,experiment['input_sha256'])
        self.assertEqual(config['old_red']['red']['test_sha256'],proof['test_sha256'])
        self.assertNotEqual(config['old_red']['red']['test_sha256'],experiment['input_sha256'])
        self.assertEqual(config['controls_completion'],proof)
        with self.db() as con:data=json.loads(con.execute('SELECT data FROM delivery_handoffs').fetchone()[0])
        with patch('broker.incremental_harness_replan.validate_experiment') as validate:
            reason=revision.review_reason(config,data)
        validate.assert_called_once_with(experiment,experiment['input_sha256'])
        self.assertIn('historical evidence',reason)
        self.assertIn('NEW methods',reason)
        altered={**data,'controls_completion':{**proof,'manifest_sha256':'0'*64}}
        with self.assertRaisesRegex(ValueError,'review lineage drift'):revision.review_reason(config,altered)

    def test_controls_revision_cannot_relabel_fixture_or_rejected_red(self):
        payload,experiment,proof=self.controls_registration_fixture()
        with self.db() as con:
            data=json.loads(con.execute('SELECT data FROM delivery_handoffs').fetchone()[0])
            data['controls_completion']['manifest_sha256']='0'*64
            con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(data),))
        with self.assertRaisesRegex(ValueError,'current rejected seed lineage'):
            revision.register(self.broker,payload)

    def test_seed_source_is_controller_bound_and_legacy_trials_are_not_reseeded(self):
        payload = self.registration_fixture()
        revision.register(self.broker, payload)
        with self.db() as con:
            config = json.loads(con.execute('SELECT config FROM test_revision_trials').fetchone()[0])
            config['old_red']['red']['manifest_sha256'] = 'e' * 64
            con.execute('UPDATE test_revision_trials SET config=?', (json.dumps(config),))
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'owner',
                                                  'delivery-kit.test-first-task': 'old-tests'}}
        selected = revision.seed_source(self.broker, payload['issue_id'])
        self.assertEqual(selected['mount'], {'Type': 'volume', 'Source': 'historic',
                                           'Target': '/previous', 'ReadOnly': True})
        self.assertEqual(selected['selection']['manifest_sha256'], 'e' * 64)
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'foreign'}}
        with self.assertRaisesRegex(ValueError, 'identity'):
            revision.seed_source(self.broker, payload['issue_id'])
        config.pop('seed_previous_tests')
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET config=?', (json.dumps(config),))
        self.assertIsNone(revision.seed_source(self.broker, payload['issue_id']))

    def test_seed_source_rejects_changed_author_and_base(self):
        payload = self.registration_fixture()
        revision.register(self.broker, payload)
        self.broker.issue_base = lambda _: {'base_sha': 'c' * 40}
        with self.assertRaisesRegex(ValueError, 'lineage'):
            revision.seed_source(self.broker, payload['issue_id'])
        self.broker.issue_base = lambda _: {'base_sha': 'b' * 40}
        with self.db() as con:
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                            (payload['issue_id'],)).fetchone()[0])
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
                        (json.dumps({**route, 'author': 'other'}), payload['issue_id']))
        with self.assertRaisesRegex(ValueError, 'lineage'):
            revision.seed_source(self.broker, payload['issue_id'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.broker = SimpleNamespace(db=self.db, OWNER='owner', docker=lambda *_: None)
        self.route = {'issue_id': 'child', 'author': 'author', 'techlead': 'lead', 'cto': 'cto',
                      'test_first_files': ['tests/test_new.py'], 'minimum_calls': 8}
        self.red = {'task_id': 'new-tests', 'volume': 'candidate',
                    'red': {'manifest_sha256': 'a' * 64}}
        self.config = {'reviewer': 'lead', 'reason': 'Correct DOM coercion and invalid count.',
                       'old_red': {'volume': 'old-frozen', 'task_id': 'old-tests',
                                   'red': {'test_sha256': {'tests/test_new.py': 'a' * 64}}}}
        self.created = {}
        self.effects = SimpleNamespace(remaining_calls=lambda: 64, ensure_wakeup=self.wakeup,
                                       decision=lambda task: task['decision'], read_evidence=lambda _: {
                                           '/evidence/candidate/tests/test_new.py': {'call_id': 'candidate'},
                                           '/evidence/previous/tests/test_new.py': {'call_id': 'previous'}})
        with self.db() as con:
            handoffs.initialize(con)
            revision.initialize(con)
            con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',
                        ('child', 'parent', json.dumps(self.config), '{}'))
            con.execute('CREATE TABLE native_bindings(request_id TEXT,issue_id TEXT,agent_id TEXT)')
            con.execute("INSERT INTO native_bindings VALUES ('request','child','lead')")

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def wakeup(self, issue, target, source, marker, instruction, **kwargs):
        self.last_instruction = instruction
        if not kwargs.get('allow_create', True):
            return None
        self.created.setdefault(marker, {'id': 'wake'})
        return self.created[marker]

    def reviewer(self, action='approve_test_revision', digest='a' * 64, actor='lead'):
        return {'id': 'independent-review', 'agent_id': actor, 'wakeup_id': 'wake',
                'status': 'completed', 'decision': {'action': action, 'manifest_sha256': digest,
                'reason': 'Observed faithful behavior and unchanged coverage.', 'optional_files': []}}

    def test_dispatched_test_reviewer_waits_without_approval_or_failure(self):
        revision.reconcile(self.broker,self.route,[],self.effects,self.red)
        reviewer=self.reviewer();reviewer['status']='dispatched'
        self.assertFalse(revision.reconcile(self.broker,self.route,[reviewer],self.effects,self.red))
        with self.db() as con:
            state=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'],'awaiting_review')
        self.assertNotIn('decision',state)
        self.assertNotIn('review_failure',state)

    def semantic_parent(self):
        from broker.candidate_qualification import experiment_hash
        fact = {'file': 'tests/test_new.py', 'test': 'tests.test_new.Cases.test_case',
                'title': 'Σίσυφος task', 'query': 'σισυφος', 'query_line': 218,
                'casefold_substring': False}
        proof = {'facts': [fact], 'manifest_sha256': 'a' * 64, 'output_sha256': 'b' * 64}
        ack = {'experiment_sha256': experiment_hash(proof), 'semantic_checks': [
            {'fact_index': 0, 'casefold_substring': False}]}
        data = {'semantic_fixture_experiment': proof, 'candidate_qualification': {
            'stage': 'semantic_test_revision_qualified', 'sponsor_task': 'cto-decision',
            'review_decision': ack, 'sponsor_decision': ack}, 'semantic_repair_findings': {
                'experiment_sha256': experiment_hash(proof), 'manifest_sha256': 'a' * 64,
                'output_sha256': 'b' * 64, 'status': 'findings_only_not_approval',
                'contradictions': [{**fact, 'asserted_match': True}]}}
        self.config.update(parent_issue='parent', cto_decision='cto-decision')
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET config=?', (json.dumps(self.config),))
            handoffs.save(con, 'old-source', 'parent', 'test_revision_required', 'cto', data, 1)
        scope = revision.semantic_scope(data)
        receipt = {**proof, 'operation': 'python_str_strip_casefold_substring_v1',
            'fixture_literals_only': True, 'contradictions': [{**fact, 'asserted_match': True}],
            'scope_sha256': hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()}
        return receipt

    def test_semantic_gate_invalidates_prior_approval_without_retry_or_write_grant(self):
        receipt = self.semantic_parent()
        prior = {'status': 'approved', 'manifest_sha256': 'a' * 64,
                 'decision': self.reviewer()['decision'], 'review_task': 'old-review'}
        with self.db() as con:
            con.execute('UPDATE test_revision_trials SET state=?', (json.dumps(prior),))
        with patch('broker.test_revision_review.candidate_semantic_check', return_value=receipt) as probe:
            self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
            self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
            probe.assert_called_once()
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['prior_approval']['decision'], prior['decision'])
        self.assertEqual(self.created, {})

    def test_final_evidence_policy_prompt_retains_semantic_basis(self):
        receipt = self.semantic_parent()
        receipt['contradictions'] = []
        self.effects.test_review_report = lambda *args: {'files': {}}
        observed = []
        original = self.effects.ensure_wakeup
        self.effects.ensure_wakeup = lambda *args, **kwargs: (observed.append(args[4]) or original(*args, **kwargs))
        with patch('broker.test_revision_review.candidate_semantic_check', return_value=receipt):
            self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertIn('SOURCE-BOUND REVISION BASIS', observed[0])
        self.assertIn('accent-preserving', observed[0])

    def test_restart_then_exact_independent_approval_permits_implementation_once(self):
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertEqual(len(self.created), 1)
        self.assertTrue(revision.reconcile(self.broker, self.route, [self.reviewer()], self.effects, self.red))
        self.assertTrue(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        with self.db() as con:
            self.assertEqual(handoffs.load(con, 'new-tests')['stage'], 'test_revision_approved')

    def initial_submission(self):
        with self.db() as con:
            con.execute('DELETE FROM test_revision_trials')
        self.broker.issue_base = lambda _: {'base_sha': 'b' * 40}
        self.route['test_first_files'] = ['tests/test_new.py']
        self.red['red']['test_sha256'] = {'tests/test_new.py': 'c' * 64}

    def test_first_submission_requires_independent_review_and_survives_restart(self):
        self.initial_submission()
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertEqual(len(self.created), 1)
        with self.db() as con:
            row = con.execute('SELECT parent_issue,config FROM test_revision_trials').fetchone()
            self.assertIsNone(row['parent_issue'])
            self.assertTrue(json.loads(row['config'])['initial_review'])
        self.effects.read_evidence = lambda _: {'/evidence/candidate/tests/test_new.py': {'call_id': 'read'}}
        self.assertTrue(revision.reconcile(self.broker, self.route, [self.reviewer()], self.effects, self.red))
        self.assertTrue(revision.reconcile(self.broker, self.route, [], self.effects, self.red))

    def test_invalid_quote_automatically_creates_only_one_fresh_readonly_review(self):
        self.initial_submission()
        self.effects.test_review_report=lambda *_:{'files':{}}
        self.effects.read_evidence=lambda _:{'/evidence/candidate/tests/test_new.py':
            dict(call_id='candidate',lines=51,total_lines=51,next_offset=None)}
        revision.reconcile(self.broker,self.route,[],self.effects,self.red)
        failed=self.reviewer('reject_test_revision')
        failed['decision']['findings']=[{'quote':'incorrect source quote'}]
        with patch('broker.test_revision_review.validate_evidence',side_effect=ValueError('finding quote not observed at exact line')):
            self.assertFalse(revision.reconcile(self.broker,self.route,[failed],self.effects,self.red))
            self.assertFalse(revision.reconcile(self.broker,self.route,[failed],self.effects,self.red))
        with self.db() as con:
            state=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'],'dispatch_intent')
        self.assertEqual(state['citation_recovery']['invalid_decision'],failed['decision'])
        self.assertFalse(state['citation_recovery']['approval'])
        revision.reconcile(self.broker,self.route,[failed],self.effects,self.red)
        revision.reconcile(self.broker,self.route,[failed],self.effects,self.red)
        self.assertEqual(len(self.created),2)
        self.assertIn('Copy each quote verbatim',self.last_instruction)
        self.assertIn('SAME frozen tests',self.last_instruction)

    def test_first_submission_mounts_only_genuine_candidate_readonly(self):
        self.initial_submission()
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'owner',
                                                  'delivery-kit.test-first-task': 'new-tests'}}
        self.assertEqual(revision.planning_mounts(self.broker, 'request'), [
            {'Type': 'volume', 'Source': 'candidate', 'Target': '/evidence/candidate', 'ReadOnly': True}])

    def test_second_invalid_citation_escalates_once_without_accepting_either_verdict(self):
        self.initial_submission()
        self.effects.test_review_report=lambda *_:{'files':{}}
        self.effects.read_evidence=lambda _:{'/evidence/candidate/tests/test_new.py':
            dict(call_id='candidate',lines=51,total_lines=51,next_offset=None)}
        revision.reconcile(self.broker,self.route,[],self.effects,self.red)
        failed=self.reviewer('reject_test_revision');failed['decision']['findings']=[{'quote':'bad'}]
        with patch('broker.test_revision_review.validate_evidence',side_effect=ValueError('finding quote not observed at exact line')):
            revision.reconcile(self.broker,self.route,[failed],self.effects,self.red)
            revision.reconcile(self.broker,self.route,[failed],self.effects,self.red)
        original_wakeup=self.effects.ensure_wakeup
        self.effects.ensure_wakeup=lambda *args,**kwargs:{**original_wakeup(*args,**kwargs),'id':'fresh-wake'}
        revision.reconcile(self.broker,self.route,[failed],self.effects,self.red)
        second={**failed,'id':'second-review','wakeup_id':'fresh-wake'}
        with patch('broker.test_revision_review.validate_evidence',side_effect=ValueError('finding test or line does not exist')):
            revision.reconcile(self.broker,self.route,[second],self.effects,self.red)
            revision.reconcile(self.broker,self.route,[second],self.effects,self.red)
            revision.reconcile(self.broker,self.route,[second],self.effects,self.red)
        self.assertEqual(len(self.created),3)  # two reviews, ONE CTO diagnosis
        self.assertIn('Neither verdict was accepted',self.last_instruction)
        self.assertIn('DELIVERY_OBSERVED_FINDINGS_V1',self.last_instruction)
        with self.db() as con:
            state=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
            self.assertEqual(handoffs.load(con,'new-tests')['owner'],'cto')
        self.assertNotIn('review_task',state);self.assertNotIn('decision',state)
        self.assertFalse(state['protocol_diagnosis']['approval'])
        self.assertEqual(state['protocol_diagnosis']['failed_task'],'second-review')
        # A fresh independent CTO can sponsor new tests, never approve old tests.
        def validation(_broker,_route,_state,decision):
            if decision['action']=='reject_test_revision':raise ValueError('finding test or line does not exist')
        with patch('broker.test_revision_review.validate_evidence',side_effect=validation):
            revision.reconcile(self.broker,self.route,[second,{**self.cto(),'wakeup_id':'fresh-wake'}],self.effects,self.red)
        with self.db() as con:
            state=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'],'blocked')
        self.assertEqual(state['rejection_diagnosis']['status'],'revision_required')
        self.assertNotIn('decision',state)

    def test_first_submission_rejects_self_review_and_scope_drift(self):
        self.initial_submission()
        with self.assertRaisesRegex(ValueError, 'independent'):
            revision.reconcile(self.broker, {**self.route, 'techlead': 'author'}, [], self.effects, self.red)
        with self.assertRaisesRegex(ValueError, 'scope'):
            revision.reconcile(self.broker, {**self.route, 'test_first_files': ['other.py']}, [], self.effects, self.red)

    def test_stale_approval_is_blocked_without_weakening_or_another_wakeup(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.assertFalse(revision.reconcile(self.broker, self.route,
                         [self.reviewer(digest='b' * 64)], self.effects, self.red))
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertEqual(len(self.created), 1)

    def test_author_cannot_approve_and_changed_snapshot_invalidates_prior_approval(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.assertFalse(revision.reconcile(self.broker, self.route,
                         [self.reviewer(actor='author')], self.effects, self.red))
        revision.reconcile(self.broker, self.route, [self.reviewer()], self.effects, self.red)
        with self.assertRaisesRegex(ValueError, 'stale'):
            revision.reconcile(self.broker, self.route, [], self.effects,
                               {**self.red, 'red': {'manifest_sha256': 'c' * 64}})

    def test_artifacts_are_readonly_and_foreign_volume_is_rejected(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.broker.docker = lambda _, path: {'Labels': {
            'delivery-kit.owner': 'owner', 'delivery-kit.test-first-task':
                'new-tests' if path.endswith('candidate') else 'old-tests'}}
        mounts = revision.planning_mounts(self.broker, 'request')
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(m['ReadOnly'] for m in mounts))
        self.assertNotIn('/var/run/docker.sock', json.dumps(mounts))
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'foreign'}}
        with self.assertRaisesRegex(ValueError, 'identity'):
            revision.planning_mounts(self.broker, 'request')

    def test_diagnosis_reads_exact_failed_snapshot_and_historic_red_only(self):
        self.assert_diagnostic_mounts(historical_review=False)

    def test_structural_mounts_require_exact_receipt_base_and_owner(self):
        from broker import structural_diagnosis as structural
        proof=dict(source_task='failed',issue_id='child',candidate_volume='snapshot',base_volume='base',base_manifest_sha256='b'*64,delivery_approval=False)
        data=dict(source_task='failed',target='lead',structural_diagnosis=proof)
        with self.db() as c:
            structural.initialize(c)
            c.execute('INSERT INTO structural_diagnoses VALUES(?,?)',('failed',json.dumps(proof)))
            c.execute('CREATE TABLE snapshots(task_id,volume,status)')
            c.execute("INSERT INTO snapshots VALUES('failed','snapshot','complete')")
            handoffs.save(c,'failed','child','diagnose_cto','lead',data,100)
        self.broker.issue_base=lambda _:dict(volume='base',manifest_sha256='b'*64)
        self.broker.docker=lambda _,path:dict(Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':'failed','delivery-kit.issue-id':'child'})
        mounts=revision.diagnostic_mounts(self.broker,dict(issue_id='child',agent_id='lead'))
        self.assertEqual([m['Source'] for m in mounts],['snapshot','base'])
        self.assertTrue(all(m['ReadOnly'] for m in mounts))
        self.assertEqual(revision.diagnostic_mounts(self.broker,dict(issue_id='child',agent_id='author')),[])
        self.broker.issue_base=lambda _:dict(volume='base',manifest_sha256='0'*64)
        with self.assertRaises(ValueError):revision.diagnostic_mounts(self.broker,dict(issue_id='child',agent_id='lead'))

    def test_completed_test_review_cannot_shadow_later_suite_diagnosis(self):
        self.assert_diagnostic_mounts(historical_review=True)

    def assert_diagnostic_mounts(self, *, historical_review):
        with self.db() as con:
            if historical_review:
                con.execute('UPDATE test_revision_trials SET state=?',
                            (json.dumps({'status': 'approved'}),))
            else:
                con.execute('DELETE FROM test_revision_trials')
            con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute("INSERT INTO snapshots VALUES ('failed','snapshot','complete')")
            con.execute('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)')
            con.execute('INSERT INTO test_first_red VALUES (?,?)', ('child', json.dumps(
                {'volume': 'historic', 'task_id': 'old-tests'})))
            handoffs.save(con, 'failed', 'child', 'diagnose_cto', 'lead', {
                'target': 'lead', 'artifact_diagnosis': True,
                'validation_failure': {'source_task': 'failed', 'volume': 'snapshot'}}, 100)
        self.broker.docker = lambda _, path: {'Labels': {
            'delivery-kit.owner': 'owner', 'delivery-kit.source-task': 'failed',
            'delivery-kit.test-first-task': 'old-tests'}}
        mounts = revision.planning_mounts(self.broker, 'request')
        self.assertEqual([m['Source'] for m in mounts], ['snapshot', 'historic'])
        self.assertTrue(all(m['ReadOnly'] for m in mounts))
        self.assertEqual(revision.diagnostic_mounts(self.broker,
                         {'issue_id': 'child', 'agent_id': 'author'}), [])
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'foreign'}}
        with self.assertRaisesRegex(ValueError, 'identity'):
            revision.planning_mounts(self.broker, 'request')

    def test_rejection_is_terminal_for_this_revision_not_delivery_success(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.assertFalse(revision.reconcile(self.broker, self.route,
                         [self.reviewer(action='reject_test_revision')], self.effects, self.red))
        with self.db() as con:
            self.assertEqual(handoffs.load(con, 'new-tests')['stage'], 'test_review_cto_diagnosis')
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['review_task'], 'independent-review')
        self.assertEqual(state['rejection_diagnosis']['target'], 'cto')

    def test_failed_execution_artifact_requires_durable_receipt_and_diagnostic_label(self):
        self.assert_diagnostic_mounts(historical_review=False)
        failure = {'source_task': 'failed', 'volume': 'diagnostic'}
        receipt = {'failure': failure, 'status': 'diagnostic_only_not_approved'}
        with self.db() as con:
            con.execute('CREATE TABLE failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute("INSERT INTO failed_execution_snapshots VALUES ('failed','diagnostic','complete')")
            con.execute('CREATE TABLE failed_execution_diagnoses(source_task TEXT,receipt TEXT)')
            con.execute('INSERT INTO failed_execution_diagnoses VALUES (?,?)', ('failed', json.dumps(receipt)))
            handoffs.save(con, 'failed', 'child', 'diagnose_cto', 'lead', {
                'target': 'lead', 'artifact_diagnosis': True,
                'failed_execution_diagnostic': receipt, 'validation_failure': failure}, 200)
        labels = {'delivery-kit.owner': 'owner', 'delivery-kit.source-task': 'failed',
                  'delivery-kit.test-first-task': 'old-tests', 'delivery-kit.diagnostic-only': 'true'}
        self.broker.docker = lambda *_: {'Labels': labels}
        mounts = revision.planning_mounts(self.broker, 'request')
        self.assertEqual([m['Source'] for m in mounts], ['diagnostic', 'historic'])
        self.assertTrue(all(m['ReadOnly'] for m in mounts))
        labels.pop('delivery-kit.diagnostic-only')
        with self.assertRaisesRegex(ValueError, 'volume identity'):
            revision.planning_mounts(self.broker, 'request')
        with self.db() as con:
            con.execute('DELETE FROM failed_execution_diagnoses')
        with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
            revision.planning_mounts(self.broker, 'request')

    def rejected(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        revision.reconcile(self.broker, self.route, [self.reviewer(action='reject_test_revision')],
                           self.effects, self.red)

    def cto(self, action='request_test_revision'):
        return {'id': 'cto-diagnosis', 'agent_id': 'cto', 'status': 'completed', 'wakeup_id': 'wake',
                'decision': {'action': action, 'optional_files': [],
                             'reason': 'Preserve assertions; repair the actual event-dispatch harness.'}}

    def test_rejection_dispatch_is_idempotent_and_cto_can_only_sponsor_new_revision(self):
        self.rejected()
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.assertEqual(len(self.created), 2)
        self.assertFalse(revision.reconcile(self.broker, self.route, [self.cto()], self.effects, self.red))
        with self.db() as con:
            handoff = handoffs.load(con, 'new-tests')
            data = json.loads(handoff['data'])
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(handoff['stage'], 'test_revision_required')
        self.assertEqual(data['test_revision_proposal']['source_task'], 'new-tests')
        self.assertEqual(data['test_revision_proposal']['decision_task'], 'cto-diagnosis')
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['review_task'], 'independent-review')
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        self.assertEqual(len(self.created), 2)

    def test_cto_cannot_override_rejection_or_decide_without_inspection(self):
        self.rejected()
        self.assertFalse(revision.reconcile(self.broker, self.route,
                                          [self.cto('approve_test_revision')], self.effects, self.red))
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['rejection_diagnosis']['status'], 'blocked')

    def test_protocol_diagnosis_format_recovery_is_once_and_preserves_failure(self):
        self.initial_submission();revision.reconcile(self.broker,self.route,[],self.effects,self.red)
        with self.db() as con:state=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        state.update(status='blocked',reason='invalid_independent_test_review:ValueError',
            review_failure={'detail':'finding test or line does not exist'},
            protocol_diagnosis={'operation':'invalid_review_citation_escalation_v1'},
            rejection_diagnosis=dict(status='blocked',wakeup_id='old-cto',target='cto',
                failure=dict(task_id='failed-cto',operation='task_completion',detail='CTO diagnosis did not complete')))
        failed=dict(id='failed-cto',status='failed',agent_id='cto',wakeup_id='old-cto',
            error='hermes provider error: API call failed after 1 retries')
        self.effects.read_evidence=lambda _:{'/evidence/candidate/tests/test_new.py':dict(lines=10,total_lines=10)}
        self.effects.test_review_report=lambda *_:{'files':{}}
        state['evidence_policy']=1;state['comparison']={'files':{}}
        revision.reconcile_rejection(self.broker,self.route,[failed],self.effects,self.red,
            {'reviewer':'lead','initial_review':True},state,protocol_task='bad-review')
        receipt=state['rejection_diagnosis']['typed_transport_recovery']
        self.assertEqual(receipt['failed_task'],'failed-cto');self.assertFalse(receipt['approval'])
        self.assertIn('DELIVERY_TYPED_TEST_DIAGNOSIS_V1',self.last_instruction)
        self.assertEqual(len(self.created),2)
        # A second failure remains visible, never consumes another retry.
        state['rejection_diagnosis'].update(status='blocked',failure=receipt['prior_diagnosis']['failure'])
        revision.reconcile_rejection(self.broker,self.route,[failed],self.effects,self.red,
            {'reviewer':'lead','initial_review':True},state,protocol_task='bad-review')
        self.assertEqual(len(self.created),2)

    def test_cto_compares_rejected_revision_with_previous_readonly(self):
        self.rejected()
        with self.db() as con:
            con.execute("UPDATE native_bindings SET agent_id='cto'")
        self.broker.docker = lambda _, path: {'Labels': {'delivery-kit.owner': 'owner',
            'delivery-kit.test-first-task': 'new-tests' if path.endswith('candidate') else 'old-tests'}}
        mounts = revision.planning_mounts(self.broker, 'request')
        self.assertEqual([m['Source'] for m in mounts], ['candidate', 'old-frozen'])
        self.assertTrue(all(m['ReadOnly'] for m in mounts))

    def test_cto_cannot_sponsor_revision_without_reading_previous(self):
        self.rejected()
        self.effects.read_evidence = lambda _: {
            '/evidence/candidate/tests/test_new.py': {'call_id': 'candidate'}}
        revision.reconcile(self.broker, self.route, [self.cto()], self.effects, self.red)
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['rejection_diagnosis']['status'], 'blocked')
        self.assertEqual(state['rejection_diagnosis']['failure']['operation'], 'artifact_reads')

    def test_initial_rejection_cto_has_no_fabricated_previous(self):
        self.initial_submission()
        self.red['red']['test_sha256'] = {'tests/test_new.py': 'a' * 64}
        self.rejected()
        with self.db() as con:
            con.execute("UPDATE native_bindings SET agent_id='cto'")
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'owner',
                                                  'delivery-kit.test-first-task': 'new-tests'}}
        self.assertEqual(len(revision.planning_mounts(self.broker, 'request')), 1)
        self.effects.read_evidence = lambda _: {
            '/evidence/candidate/tests/test_new.py': {'call_id': 'candidate'}}
        revision.reconcile(self.broker, self.route, [self.cto()], self.effects, self.red)
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['rejection_diagnosis']['status'], 'revision_required')

    def test_overlong_cto_reason_records_limit_and_never_truncates(self):
        self.rejected()
        task = self.cto()
        task['decision']['reason'] = 'x' * 4315
        revision.reconcile(self.broker, self.route, [task], self.effects, self.red)
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        diagnosis = state['rejection_diagnosis']
        self.assertEqual(diagnosis['status'], 'blocked')
        self.assertEqual(diagnosis['failure']['reason_length'], 4315)
        self.assertEqual(diagnosis['failure']['reason_max_length'], 1200)
        self.assertNotIn('decision', diagnosis)

    def test_cto_missing_reads_is_blocked_without_repeating_diagnosis(self):
        self.rejected()
        self.effects.read_evidence = lambda _: {}
        self.assertFalse(revision.reconcile(self.broker, self.route, [self.cto()], self.effects, self.red))
        self.assertFalse(revision.reconcile(self.broker, self.route, [], self.effects, self.red))
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['rejection_diagnosis']['status'], 'blocked')
        self.assertEqual(len(self.created), 2)

    def test_cto_budget_pause_persists_intent_without_silent_approval(self):
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.effects.remaining_calls = lambda: 1
        revision.reconcile(self.broker, self.route, [self.reviewer(action='reject_test_revision')],
                           self.effects, self.red)
        with self.db() as con:
            state = json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['rejection_diagnosis']['status'], 'dispatch_intent')
        self.assertNotIn('wakeup_id', state['rejection_diagnosis'])
        self.effects.remaining_calls = lambda: 64
        revision.reconcile(self.broker, self.route, [], self.effects, self.red)
        self.assertEqual(len(self.created), 2)
