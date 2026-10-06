from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from broker.candidate_qualification import advance


class CandidateQualificationTests(unittest.TestCase):
    def setUp(self):
        self.config = {'request': {'source_task': 'source', 'decision_task': 'cto-old'},
            'issue_id': 'issue', 'reviewer': 'lead', 'cto': 'cto', 'required_files': ['app.py', 'tests/test_new.py'],
            'contract_sha256': 'a' * 64, 'proof': {'witnesses': [], 'manifest_sha256': 'b' * 64, 'output_sha256': 'c' * 64},
            'requirements': 'Use substring search and Unicode casefold, preserving baseline.'}
        self.effects = SimpleNamespace(ensure_wakeup=Mock(return_value={'id': 'wake'}),
            remaining_calls=Mock(return_value=64),
            read_evidence=Mock(return_value={
                '/evidence/candidate/app.py': {'lines': 10, 'total_lines': 10},
                '/evidence/candidate/tests/test_new.py': {'lines': 20, 'total_lines': 20}}),
            decision=Mock(return_value={'action': 'request_test_revision', 'reason': 'Contradictory NEW assertion', 'optional_files': []}))

    def recipient(self, who='lead', status='completed'):
        return {'id': who + '-task', 'agent_id': who, 'status': status, 'wakeup_id': 'wake'}

    def test_independent_review_then_cto_sponsorship_never_approves_delivery(self):
        state = advance(self.config, {'stage': 'review_pending'}, [], self.effects)
        self.assertEqual(state['target'], 'lead')
        state = advance(self.config, state, [self.recipient()], self.effects)
        self.assertEqual(state['stage'], 'sponsor_pending')
        self.assertEqual(state['review_task'], 'lead-task')
        state = advance(self.config, state, [], self.effects)
        self.assertEqual(state['target'], 'cto')
        state = advance(self.config, state, [self.recipient('cto')], self.effects)
        self.assertEqual(state['stage'], 'qualified_test_revision')
        self.assertNotIn('approval', state)
        self.assertEqual(advance(self.config, state, [], self.effects), state)

    def test_incomplete_read_is_blocked_without_duplicate_retry(self):
        state = advance(self.config, {'stage': 'review_pending'}, [], self.effects)
        self.effects.read_evidence.return_value = {}
        state = advance(self.config, state, [self.recipient()], self.effects)
        self.assertEqual(state['stage'], 'blocked')
        self.effects.decision.assert_not_called()
        self.assertEqual(advance(self.config, state, [], self.effects), state)
        self.effects.ensure_wakeup.assert_called_once()

    def test_prose_correction_cannot_grant_author_access(self):
        state = advance(self.config, {'stage': 'review_pending'}, [], self.effects)
        self.effects.decision.return_value['action'] = 'request_correction'
        state = advance(self.config, state, [self.recipient()], self.effects)
        self.assertEqual(state['stage'], 'blocked')

    def test_budget_exhaustion_does_not_spawn(self):
        self.effects.ensure_wakeup.return_value = None
        self.effects.remaining_calls.return_value = 0
        state = advance(self.config, {'stage': 'review_pending'}, [], self.effects)
        self.assertNotIn('wakeup_id', state)
        self.assertFalse(self.effects.ensure_wakeup.call_args.kwargs['allow_create'])

    def test_failed_execution_stays_visible(self):
        state = advance(self.config, {'stage': 'review_pending'}, [], self.effects)
        state = advance(self.config, state, [self.recipient(status='failed')], self.effects)
        self.assertEqual(state['stage'], 'blocked')
        self.assertEqual(state['task'], 'lead-task')

    def test_semantic_checks_must_match_all_experiment_facts_exactly(self):
        from broker.candidate_qualification import validate_semantic_checks
        proof = {'facts': [{'casefold_substring': True}, {'casefold_substring': False}],
                 'manifest_sha256': 'a' * 64}
        import hashlib, json
        digest = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        decision = {'experiment_sha256': digest, 'semantic_checks': [
            {'fact_index': 0, 'casefold_substring': True},
            {'fact_index': 1, 'casefold_substring': False}]}
        validate_semantic_checks(decision, proof)
        for checks in ([decision['semantic_checks'][0]],
                       [decision['semantic_checks'][0]] * 2,
                       [{'fact_index': 0, 'casefold_substring': False}, decision['semantic_checks'][1]],
                       [{'fact_index': 0, 'casefold_substring': 1}, decision['semantic_checks'][1]]):
            with self.assertRaises(ValueError):
                validate_semantic_checks({**decision, 'semantic_checks': checks}, proof)
        with self.assertRaises(ValueError):
            validate_semantic_checks({**decision, 'experiment_sha256': 'b' * 64}, proof)

    def test_repair_findings_require_exact_experiment_source_and_new_test(self):
        from broker.candidate_qualification import validate_repair_findings, experiment_hash
        fact = {'file': 'tests/test_new.py', 'query_line': 187, 'query': 'fix',
                'title': 'prefix', 'casefold_substring': True}
        proof = {'facts': [fact], 'manifest_sha256': 'a' * 64, 'output_sha256': 'b' * 64}
        findings = {'experiment_sha256': experiment_hash(proof), 'manifest_sha256': 'a' * 64,
                    'output_sha256': 'b' * 64, 'status': 'findings_only_not_approval',
                    'contradictions': [{**fact, 'asserted_match': False}]}
        self.assertEqual(validate_repair_findings(findings, proof, ['tests/test_new.py']), findings['contradictions'])
        for invalid in (None, {**findings, 'output_sha256': 'c' * 64},
                        {**findings, 'contradictions': []},
                        {**findings, 'contradictions': [{**fact, 'asserted_match': True}]},
                        {**findings, 'contradictions': findings['contradictions'] * 2}):
            with self.assertRaises(ValueError):
                validate_repair_findings(invalid, proof, ['tests/test_new.py'])
        with self.assertRaises(ValueError):
            validate_repair_findings(findings, proof, ['tests/test_old.py'])

    def test_semantic_review_and_sponsorship_gate_proposal(self):
        from broker.candidate_qualification import experiment_hash
        proof = {'facts': [{'casefold_substring': True, 'query_line': 1, 'query': 'fix', 'title': 'prefix'}],
                 'manifest_sha256': 'a' * 64}
        state = {'stage': 'semantic_review_pending', 'semantic_experiment': proof,
                 'prior_qualification': {'sponsor_task': 'old-cto'}}
        self.effects.decision.return_value.update(experiment_sha256=experiment_hash(proof),
            semantic_checks=[{'fact_index': 0, 'casefold_substring': True}])
        state = advance(self.config, state, [], self.effects)
        note = self.effects.ensure_wakeup.call_args.args[4]
        self.assertIn('DELIVERY_SEMANTIC_CHECKS_V1', note)
        state = advance(self.config, state, [self.recipient()], self.effects)
        self.assertEqual(state['stage'], 'semantic_sponsor_pending')
        state = advance(self.config, state, [], self.effects)
        state = advance(self.config, state, [self.recipient('cto')], self.effects)
        self.assertEqual(state['stage'], 'semantic_test_revision_qualified')

    def test_wrong_semantic_ack_is_terminal_without_write_grant(self):
        from broker.candidate_qualification import experiment_hash
        proof = {'facts': [{'casefold_substring': True, 'query_line': 1, 'query': 'fix', 'title': 'prefix'}],
                 'manifest_sha256': 'a' * 64}
        state = {'stage': 'semantic_review_pending', 'semantic_experiment': proof,
                 'prior_qualification': {'sponsor_task': 'old-cto'}}
        self.effects.decision.return_value.update(experiment_sha256=experiment_hash(proof),
            semantic_checks=[{'fact_index': 0, 'casefold_substring': False}])
        state = advance(self.config, state, [], self.effects)
        state = advance(self.config, state, [self.recipient()], self.effects)
        self.assertEqual(state['stage'], 'blocked')
        self.assertEqual(advance(self.config, state, [], self.effects), state)
        self.effects.ensure_wakeup.assert_called_once()
