from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock
from dependent_sequence import reconcile_compiled_successor_dispatch

from dependent_sequence import ensure_cards, reconcile_compiled_predispatch, activate_compiled_cards


class CompiledCardHandoffTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'name': 'NEW-1-DELIVERY', 'stages': [
            {'spec': {'label': 'NEWAPI-1', 'title': 'API', 'description': 'API scope'}},
            {'spec': {'label': 'NEWUI-1', 'title': 'UI', 'description': 'UI scope'}}]}
        self.cards = {'C1': 'first', 'C2': 'second'}
        self.board = {'first': {'id': 'first', 'title': 'API', 'description': 'API scope',
                                'status': 'blocked', 'assignee_id': None},
                      'second': {'id': 'second', 'title': 'UI', 'description': 'UI scope',
                                 'status': 'blocked', 'assignee_id': None}}

    def cli(self, *args):
        if args[0] == 'get':
            return self.board[args[1]]
        if args[0] == 'runs':
            return []
        if args[:2] == ('metadata', 'list'):
            return {}
        if args[:2] == ('metadata', 'set'):
            return {}
        self.fail('must not search or recreate compiled native cards: ' + str(args))

    def test_exact_compiled_ids_are_reused_without_list_or_create(self):
        ledger = {}
        issue = Mock(side_effect=AssertionError('duplicate issue creation'))
        ensure_cards(self.plan, self.cli, issue, ledger, Mock(), Path('/unused'), pinned_cards=self.cards)
        self.assertEqual(ledger['issues'], {'NEWAPI-1': 'first', 'NEWUI-1': 'second'})
        issue.assert_not_called()

    def test_pre_dispatch_reconciliation_is_bounded_and_does_not_approve_delivery(self):
        failed = {'stage': 'blocked', 'active': None, 'completed': [],
                  'category': 'CalledProcessError: create conflict'}
        recovered = reconcile_compiled_predispatch(failed, self.plan, self.cards, self.cli)
        self.assertEqual(recovered['stage'], 'planned')
        self.assertIs(recovered['compiled_predispatch_reconciliation']['delivery_approved'], False)
        recovered.update(stage='blocked', category=failed['category'])
        self.assertIsNone(reconcile_compiled_predispatch(recovered, self.plan, self.cards, self.cli))

    def test_changed_card_or_existing_worker_cannot_be_reconciled(self):
        failed = {'stage': 'blocked', 'active': None, 'completed': [], 'category': 'CalledProcessError: conflict'}
        self.board['first']['assignee_id'] = 'author'
        with self.assertRaisesRegex(ValueError, 'activity'):
            reconcile_compiled_predispatch(failed, self.plan, self.cards, self.cli)

    def test_scopes_must_still_match_exactly(self):
        self.board['second']['description'] = 'Wider code scope'
        with self.assertRaisesRegex(ValueError, 'identity'):
            ensure_cards(self.plan, self.cli, Mock(), {}, Mock(), Path('/unused'), pinned_cards=self.cards)

    def test_planned_dispatch_mismatch_only_recovers_with_no_context_or_runs(self):
        failed = {'stage': 'blocked', 'active': 'NEWAPI-1', 'completed': [],
                  'issues': {'NEWAPI-1': 'first', 'NEWUI-1': 'second'},
                  'category': 'RuntimeError:stage dispatch failed: NEWAPI-1'}
        self.assertIsNone(reconcile_compiled_predispatch(failed, self.plan, self.cards, self.cli, no_context=False))
        recovered = reconcile_compiled_predispatch(failed, self.plan, self.cards, self.cli)
        self.assertEqual(recovered['stage'], 'planned')
        self.assertIn('compiled_dispatch_reconciliation', recovered)

    def test_successor_dispatch_recovery_requires_live_predecessor_and_is_bounded(self):
        failed = {'stage': 'blocked', 'active': 'NEWUI-1', 'completed': ['NEWAPI-1'],
                  'issues': {'NEWAPI-1': 'first', 'NEWUI-1': 'second'},
                  'category': 'RuntimeError:stage dispatch failed: NEWUI-1'}
        with tempfile.TemporaryDirectory() as directory:
            verify, ci = Mock(), Mock()
            kwargs = dict(read_delivery=lambda *_: {'merge_sha': 'a'*40},
                          identity=lambda *_: True, verify=verify, verify_ci=ci)
            result = reconcile_compiled_successor_dispatch(failed, self.plan, self.cards,
                self.cli, Path(directory), **kwargs)
            self.assertEqual(result['completed'], ['NEWAPI-1'])
            self.assertFalse(result['compiled_successor_dispatch_reconciliation']['delivery_approved'])
            verify.assert_called_once()
            self.assertTrue(verify.call_args.kwargs['require_live_qa'])
            ci.assert_called_once()
            result.update(stage='blocked', active='NEWUI-1', category=failed['category'])
            self.assertIsNone(reconcile_compiled_successor_dispatch(result, self.plan,
                self.cards, self.cli, Path(directory), **kwargs))
            (Path(directory)/'portable-context-NEWUI-1.json').write_text('{}')
            self.assertIsNone(reconcile_compiled_successor_dispatch(failed, self.plan,
                self.cards, self.cli, Path(directory), **kwargs))

    def test_successor_with_existing_execution_cannot_resume_as_predispatch(self):
        failed = {'stage': 'blocked', 'active': 'NEWUI-1', 'completed': ['NEWAPI-1'],
                  'issues': {'NEWAPI-1': 'first', 'NEWUI-1': 'second'},
                  'category': 'RuntimeError:stage dispatch failed: NEWUI-1'}
        def cli(*args):
            return [{'id':'existing'}] if args[0]=='runs' else self.cli(*args)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'activity'):
                reconcile_compiled_successor_dispatch(failed, self.plan, self.cards,
                    cli, Path(directory))

    def activation_fixture(self, root):
        folder = root / 'compiled-plans'
        folder.mkdir()
        (folder / 'NEW-1.json').write_text(json.dumps({'plan_sha256': 'a' * 64}))
        metadata = {key: {'planning_sha256': 'a' * 64, 'execution_gate': 'awaiting_bootstrap_contract'}
                    for key in self.board}
        changes = []
        def cli(*args):
            if args[:2] == ('metadata', 'list'):
                return metadata[args[2]]
            if args[:2] == ('metadata', 'set'):
                changes.append(args)
                metadata[args[2]][args[4]] = args[6]
                return {}
            if args[0] == 'status':
                changes.append(args)
                self.board[args[1]]['status'] = args[2]
                return self.board[args[1]]
            return self.cli(*args)
        return cli, metadata, changes

    def test_compilation_promotes_gate_but_dispatch_itself_releases_the_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli, meta, changes = self.activation_fixture(root)
            self.board['first']['status'] = 'todo'
            sha = activate_compiled_cards(root, self.plan, self.cards, cli)
            self.assertEqual(sha, 'a' * 64)
            self.assertEqual(self.board['first']['status'], 'blocked')
            self.assertTrue(all(m['execution_gate'] == 'awaiting_generated_contract' for m in meta.values()))
            self.assertNotIn(('assign',), [c[:1] for c in changes])

    def test_second_card_drift_prevents_any_gate_or_status_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli, meta, changes = self.activation_fixture(root)
            meta['second']['planning_sha256'] = 'b' * 64
            with self.assertRaisesRegex(ValueError, 'precondition'):
                activate_compiled_cards(root, self.plan, self.cards, cli)
            self.assertEqual(changes, [])
