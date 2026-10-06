import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from broker.assertion_replan import advance, validate_result, validated_record
from broker.candidate_qualification import experiment_hash


class AssertionReplanTests(unittest.TestCase):
    def setUp(self):
        self.proof = {'facts': [{'file': 'tests/test_new.py', 'test': 'tests.test_new.Cases.test_unicode',
            'query_line': 218, 'query': 'σισυφος', 'title': 'Σίσυφος task', 'casefold_substring': False}],
            'manifest_sha256': 'a' * 64, 'contradictions': [{'query_line': 218}]}
        self.config = {'source_task': 'source', 'issue_id': 'issue', 'cto': 'cto',
            'contract_sha256': 'b' * 64, 'prior_decision_task': 'old-cto', 'output_sha256': 'c' * 64,
            'proof': self.proof, 'required_files': ['app/server.py', 'tests/test_new.py'],
            'requirements': 'Plain casefold, never remove accents.'}
        self.decision = {'action': 'request_test_revision', 'reason': 'Correct all NEW assertions.',
            'optional_files': [], 'experiment_sha256': experiment_hash(self.proof),
            'semantic_checks': [{'fact_index': 0, 'casefold_substring': False}]}
        self.reads = { '/evidence/candidate/' + p: {'lines': 10, 'total_lines': 10}
                       for p in self.config['required_files'] }
        self.task = {'id': 'new-cto', 'agent_id': 'cto', 'status': 'completed', 'wakeup_id': 'wake'}
        self.effects = SimpleNamespace(ensure_wakeup=Mock(return_value={'id': 'wake'}),
            remaining_calls=Mock(return_value=48), decision=Mock(return_value=self.decision),
            read_evidence=Mock(return_value=self.reads))

    def test_replan_has_exact_proof_and_returns_certificate_not_delivery_approval(self):
        state = advance(self.config, {'stage': 'pending'}, [], self.effects)
        note = self.effects.ensure_wakeup.call_args.args[4]
        self.assertIn('DELIVERY_SEMANTIC_CHECKS_V1', note)
        self.assertIn('Contradictory assertion lines: [218]', note)
        self.assertLess(len(note) + 100, 4000)
        state = advance(self.config, state, [self.task], self.effects)
        self.assertEqual(state['stage'], 'qualified')
        self.assertEqual(state['certificate']['read_contract'], 'complete-lines-v2')
        self.assertFalse(state['certificate']['baseline_edits_allowed'])
        self.assertNotIn('approval', state)
        self.assertEqual(advance(self.config, state, [], self.effects), state)
        self.effects.ensure_wakeup.assert_called_once()

    def test_false_ack_and_incomplete_reads_block_without_repeated_wakeup(self):
        for wrong in ('ack', 'reads'):
            with self.subTest(wrong=wrong):
                state = advance(self.config, {'stage': 'pending'}, [], self.effects)
                if wrong == 'ack':
                    self.effects.decision.return_value = {**self.decision,
                        'semantic_checks': [{'fact_index': 0, 'casefold_substring': True}]}
                else:
                    self.effects.decision.return_value = self.decision
                    self.effects.read_evidence.return_value = {**self.reads,
                        '/evidence/candidate/app/server.py': {'lines': 3, 'total_lines': 10}}
                state = advance(self.config, state, [self.task], self.effects)
                self.assertEqual(state['stage'], 'blocked')
                calls = self.effects.ensure_wakeup.call_count
                self.assertEqual(advance(self.config, state, [self.task], self.effects), state)
                self.assertEqual(self.effects.ensure_wakeup.call_count, calls)

    def test_old_task_or_other_role_cannot_supply_new_replan(self):
        for task in ({**self.task, 'id': 'old-cto'}, {**self.task, 'agent_id': 'author'}):
            with self.assertRaises(ValueError):
                validate_result(self.config, task, self.decision, self.reads)

    def test_record_drift_cannot_open_another_revision(self):
        state = advance(self.config, {'stage': 'pending'}, [], self.effects)
        state = advance(self.config, state, [self.task], self.effects)
        data = {'assertion_replan': {**state, 'config': self.config},
            'technical_replan_certificate': state['certificate'], 'source_task': 'source',
            'test_revision_proposal': {'decision_task': 'new-cto'}, 'candidate_assertion_check': self.proof}
        self.assertEqual(validated_record(data), self.proof)
        changed = json.loads(json.dumps(data))
        changed['technical_replan_certificate']['decision_task'] = 'other'
        with self.assertRaises(ValueError):
            validated_record(changed)

    def test_budget_and_duplicate_recipient_fail_closed(self):
        self.effects.remaining_calls.return_value = 0
        advance(self.config, {'stage': 'pending'}, [], self.effects)
        self.assertFalse(self.effects.ensure_wakeup.call_args.kwargs['allow_create'])
        state = advance(self.config, {'stage': 'pending', 'wakeup_id': 'wake', 'at': 1},
                        [self.task, {**self.task, 'id': 'duplicate'}], self.effects)
        self.assertEqual(state['stage'], 'blocked')
