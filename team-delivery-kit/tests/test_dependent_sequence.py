import copy
import hashlib
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch, Mock

from dependent_sequence import (ensure_cards, load_plan,
                                protection_transition_allowed, receipt_identity,
                                run_sequence, release_first_card)
from dependent_sequence import read_stage_delivery, qa_stage_delivery


PLAN = (Path(__file__).resolve().parents[1] / 'projects' /
        'descartavel2-dependent-sequence.json')


class DependentSequenceTests(unittest.TestCase):
    def test_qa_child_propagates_without_approving_failed_parent_or_losing_browser_gate(self):
        from test_portable_qa_repair import CONTRACT, SPEC, INCIDENT, DIAGNOSIS
        from portable_qa_repair import derive
        browser = {'scenario': 'feedback-board-filter-v1', 'browser_image': 'sha256:' + 'b' * 64}
        spec = {**SPEC, 'browser_qa': browser,
                'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}}
        incident = {**INCIDENT, 'phase': 'browser'}
        contract, child_spec = derive(incident, CONTRACT, spec, CONTRACT['files'], DIAGNOSIS)
        stage = {'contract': CONTRACT, 'spec': {**spec, 'label': incident['label']}}
        context = {'issue_id': incident['parent_issue_id'], 'label': incident['label']}
        failed = {'issue_id': context['issue_id'], 'merge_sha': incident['source_sha']}
        sha = 'c' * 40
        child = {'issue_id': 'repair', 'label': child_spec['label'], 'stage': 'deployed_qa_passed',
                 'base_sha': incident['source_sha'], 'merge_sha': sha,
                 'contract_sha256': hashlib.sha256(json.dumps(contract, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest(),
                 'frozen_tests': {'status': 'passed'}, 'deployment': {'source_sha': sha},
                 'board': {'status': 'done'}, 'browser_qa': {'status': 'passed',
                   'cleanup': 'passed', 'automated': True,
                   'identity': {'source_sha': sha, 'config': browser}, 'result': {'source_sha': sha}}}
        proof = {'incident': incident, 'child_issue_id': 'repair',
                 'recovery': {'stage': 'qa_recovered_by_child','label': child['label'],'merge_sha': sha}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'qa-repairs').mkdir(); (root/'release-receipts').mkdir()
            (root/'qa-repairs'/(incident['key']+'.contract.json')).write_text(json.dumps(contract))
            path = root/'release-receipts'/(child['label']+'.json')
            path.write_text(json.dumps(child))
            got = qa_stage_delivery(root,stage,context,failed,proof)
            self.assertEqual(got['label'],child['label'])
            self.assertEqual(got['recovery_kind'],'qa')
            self.assertTrue(receipt_identity(got,stage))
            child['browser_qa']['identity']['config'] = {**browser, 'scenario':'feedback-board-v1'}
            path.write_text(json.dumps(child))
            with self.assertRaisesRegex(ValueError,'browser'):
                qa_stage_delivery(root,stage,context,failed,proof)

    def test_sequence_reads_proven_child_without_relabelling_its_delivery(self):
        stage = load_plan(PLAN)['stages'][1]
        label = stage['spec']['label']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('release-receipts', 'test-revision-recovery'):
                (root / folder).mkdir()
            contract_sha = hashlib.sha256(json.dumps(stage['contract'], sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()
            context = {'issue_id': 'parent', 'label': label, 'base_sha': 'base',
                       'contract_sha256': contract_sha}
            child = {'issue_id': 'child', 'label': 'TESTREVABCDEF123456-1', 'base_sha': 'base',
                     'contract_sha256': contract_sha, 'stage': 'deployed_qa_passed',
                     'merge_sha': 'a' * 40, 'deployment': {'source_sha': 'a' * 40},
                     'frozen_tests': {'status': 'passed'}, 'board': {'status': 'done'},
                     'browser_qa': {'status': 'passed', 'cleanup': 'passed', 'automated': True,
                                    'identity': {'source_sha': 'a' * 40},
                                    'result': {'source_sha': 'a' * 40}}}
            (root / ('portable-context-' + label + '.json')).write_text(json.dumps(context))
            (root / ('release-receipts/' + child['label'] + '.json')).write_text(json.dumps(child))
            intent = {'parent_issue': 'parent', 'child_issue': 'child', 'label': child['label'],
                      'stage': 'recovered_by_test_revision', 'merge_sha': child['merge_sha'],
                      'parent_board': {'status': 'done', 'via': 'test_revision_child',
                                       'child_issue': 'child', 'merge_sha': child['merge_sha']}}
            path = root / 'test-revision-recovery/parent.json'
            path.write_text(json.dumps(intent))
            got = read_stage_delivery(root, stage)
            self.assertEqual(got['label'], child['label'])
            self.assertEqual(got['recovery_parent'], context)
            self.assertTrue(receipt_identity(got, stage))
            # No forged intermediate release receipt: resolve its exact leaf.
            middle_label = 'TESTREV111111111111-1'
            middle = {**context, 'issue_id': 'middle', 'label': middle_label}
            (root / ('portable-context-' + middle_label + '.json')).write_text(json.dumps(middle))
            middle_intent = {**intent, 'parent_issue': 'middle'}
            middle_path = root / 'test-revision-recovery/middle.json'
            middle_path.write_text(json.dumps(middle_intent))
            nested = {**intent, 'child_issue': 'middle', 'label': middle_label,
                      'parent_board': {**intent['parent_board'], 'child_issue': 'middle'}}
            path.write_text(json.dumps(nested))
            got = read_stage_delivery(root, stage)
            self.assertEqual(got['issue_id'], 'child')
            self.assertEqual(got['recovery_parent'], context)
            self.assertTrue(receipt_identity(got, stage))
            middle_intent['merge_sha'] = 'b' * 40
            middle_path.write_text(json.dumps(middle_intent))
            with self.assertRaisesRegex(ValueError, 'recovery'):
                read_stage_delivery(root, stage)
            middle_intent['merge_sha'] = child['merge_sha']
            middle_path.write_text(json.dumps(middle_intent))
            cycle = {**middle_intent, 'child_issue': 'middle', 'label': middle_label}
            middle_path.write_text(json.dumps(cycle))
            with self.assertRaisesRegex(ValueError, 'cyclic'):
                read_stage_delivery(root, stage)
            intent['merge_sha'] = 'b' * 40
            path.write_text(json.dumps(intent))
            with self.assertRaisesRegex(ValueError, 'recovery'):
                read_stage_delivery(root, stage)

    def test_first_card_release_is_explicit_and_idempotent(self):
        from unittest.mock import Mock
        for status in ('blocked', 'todo'):
            cli = Mock(return_value={'id': 'first', 'status': status, 'assignee_id': None})
            release_first_card(cli, 'first')
            self.assertEqual(cli.call_count, 2 if status == 'blocked' else 1)
            if status == 'blocked':
                cli.assert_called_with('status', 'first', 'todo', '--no-start')

    def test_first_card_release_rejects_changed_ownership_or_state(self):
        from unittest.mock import Mock
        for status, owner in (('blocked', 'agent'), ('done', None), ('in_progress', None)):
            cli = Mock(return_value={'id': 'first', 'status': status, 'assignee_id': owner})
            with self.assertRaisesRegex(ValueError, 'changed before release'):
                release_first_card(cli, 'first')
            self.assertEqual(cli.call_count, 1)

    def test_successor_can_unlock_prior_frozen_code_but_not_tests(self):
        first = {'protected_files': ['app.js', 'old_test.py'],
                 'test_files': ['old_test.py']}
        second = {'protected_files': ['old_test.py'],
                  'editable_files': ['app.js', 'new_test.py']}
        self.assertTrue(protection_transition_allowed(first, second))
        second['protected_files'] = []
        second['editable_files'].append('old_test.py')
        self.assertFalse(protection_transition_allowed(first, second))

    def test_successor_card_is_visible_but_blocked(self):
        plan = load_plan(PLAN)
        cards = []
        metadata = {}
        def issue(title, description):
            card = {'id': 'first', 'title': title, 'description': description}
            cards.append(card)
            return card
        def cli(*args):
            if args[0] == 'list':
                return {'issues': cards}
            if args[0] == 'create':
                self.assertEqual(args[-2:], ('--status', 'blocked'))
                card = {'id': 'second', 'title': args[2], 'description': args[4],
                        'status': 'blocked', 'assignee_id': None}
                cards.append(card)
                return card
            if args[:2] == ('metadata', 'list'):
                return metadata.setdefault(args[2], {})
            if args[:2] == ('metadata', 'set'):
                metadata.setdefault(args[2], {})[args[4]] = args[6]
                return {}
            raise AssertionError(args)
        ledger = {}
        result = ensure_cards(plan, cli, issue, ledger, lambda *_: None, Path('/tmp/unused'))
        self.assertEqual(result, {'DEP-1': 'first', 'DEP-2': 'second'})
        self.assertEqual(cards[1]['status'], 'blocked')
        self.assertEqual(metadata['second']['depends_on_issue_id'], 'first')

    def test_plan_freezes_predecessor_test_in_successor(self):
        plan = load_plan(PLAN)
        self.assertEqual([stage['spec']['label'] for stage in plan['stages']],
                         ['DEP-1', 'DEP-2'])
        self.assertIn('node_fixture/tests/progress.test.js',
                      plan['stages'][1]['contract']['protected_files'])

    def test_success_requires_same_sha_qa_and_board(self):
        stage = load_plan(PLAN)['stages'][0]
        receipt = {'stage': 'deployed_qa_passed', 'label': 'DEP-1',
                   'merge_sha': 'a' * 40, 'deployment': {'source_sha': 'a' * 40},
                   'frozen_tests': {'status': 'passed'}, 'board': {'status': 'done'}}
        self.assertTrue(receipt_identity(receipt, stage))
        for path, value in (('stage', 'waiting_approval'), ('merge_sha', 'b' * 40),
                            ('deployment', {'source_sha': 'b' * 40}),
                            ('frozen_tests', {'status': 'failed'}),
                            ('board', {'status': 'blocked'})):
            broken = copy.deepcopy(receipt)
            broken[path] = value
            self.assertFalse(receipt_identity(broken, stage))

    def test_blocked_sequence_resumes_only_from_verified_recovery_and_preserves_incident(self):
        from dependent_sequence import resume_verified_recovery
        plan = load_plan(PLAN)
        stage = plan['stages'][0]
        ledger = {'stage': 'blocked', 'plan_sha256': plan['sha256'], 'active': 'DEP-1',
                  'completed': [], 'issues': {'DEP-1': 'parent'}, 'owner': 'techlead',
                  'category': 'RuntimeError:technical_decision_required', 'next_action': 'Resolve incident'}
        receipt = {'stage': 'deployed_qa_passed', 'label': 'TESTREVABCDEF123456-1',
            'issue_id': 'child', 'base_sha': 'base', 'contract_sha256': 'contract',
            'recovery_parent': {'issue_id': 'parent', 'label': 'DEP-1', 'base_sha': 'base', 'contract_sha256': 'contract'},
            'merge_sha': 'a' * 40, 'deployment': {'source_sha': 'a' * 40},
            'frozen_tests': {'status': 'passed'}, 'board': {'status': 'done'}, 'pr_url': 'https://github.com/example/repo/pull/1'}
        verify, ci = Mock(), Mock()
        resumed = resume_verified_recovery(ledger, plan, '/unused',
            read_delivery=lambda *_: receipt, verify=verify, verify_ci=ci)
        self.assertEqual(resumed['completed'], ['DEP-1'])
        self.assertEqual(resumed['stage'], 'stage_complete')
        self.assertEqual(resumed['resolved_incidents'][0]['category'], ledger['category'])
        self.assertEqual(ledger['stage'], 'blocked')
        verify.assert_called_once_with(receipt, stage, allow_advanced_main=False, require_live_qa=True)
        ci.assert_called_once()
        with self.assertRaises(ValueError):
            resume_verified_recovery(ledger, plan, '/unused', read_delivery=lambda *_: receipt,
                verify=Mock(side_effect=ValueError('stale board')), verify_ci=ci)
        wrong = {**receipt, 'recovery_parent': {**receipt['recovery_parent'], 'issue_id': 'unrelated'}}
        self.assertIsNone(resume_verified_recovery(ledger, plan, '/unused', read_delivery=lambda *_: wrong))
        self.assertIsNone(resume_verified_recovery({**ledger, 'category': 'cancelled_by_ceo'}, plan, '/unused',
                                                 read_delivery=lambda *_: receipt))

    def test_unavailable_recheck_does_not_revoke_completed_delivery(self):
        import evalctl
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            ledger = private / 'dependent-sequences' / 'NODE-DEPEND-1.json'
            ledger.parent.mkdir()
            ledger.write_text(json.dumps({'sequence': 'NODE-DEPEND-1',
                'plan_sha256': load_plan(PLAN)['sha256'], 'stage': 'done',
                'completed': ['DEP-1', 'DEP-2']}))
            with patch.dict('os.environ', {'DELIVERY_KIT_SEQUENCE_PLAN': str(PLAN)}), \
                    patch.object(evalctl, 'PRIVATE', private), \
                    patch.object(evalctl, 'PROJECT', 'delivery-kit-port2'), \
                    patch('dependent_sequence.verify_predecessor',
                          side_effect=ValueError('temporary QA outage')):
                self.assertEqual(run_sequence(), 2)
            self.assertEqual(json.loads(ledger.read_text())['stage'], 'done')


if __name__ == '__main__':
    unittest.main()
