import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hashlib
import json

import portable_delivery
from portable_qa_incident import QualityBlocked, failing_case, find, record
from portable_qualification import qa_case_failure


PARENT = '11111111-1111-4111-8111-111111111111'
CHILD = '22222222-2222-4222-8222-222222222222'
TECHLEAD = '33333333-3333-4333-8333-333333333333'
SHA = 'a' * 40


class FakeCLI:
    def __init__(self):
        self.parent = {'id': PARENT, 'title': 'Delivery', 'status': 'todo',
                       'metadata': {}, 'assignee_id': None}
        self.child = None
        self.created = 0
        self.started = 0
        self.runs = []

    def __call__(self, command, *args):
        if command == 'search':
            return {'issues': [self.parent] + ([self.child] if self.child else [])}
        if command == 'create':
            self.created += 1
            self.child = {'id': CHILD, 'title': args[args.index('--title') + 1],
                          'parent_issue_id': PARENT, 'status': 'blocked',
                          'metadata': {}, 'assignee_id': None}
            return self.child
        if command == 'get':
            return self.parent if args[0] == PARENT else self.child
        if command == 'metadata' and args[0] == 'list':
            return (self.parent if args[1] == PARENT else self.child)['metadata']
        if command == 'metadata' and args[0] == 'set':
            issue = self.parent if args[1] == PARENT else self.child
            issue['metadata'][args[args.index('--key') + 1]] = args[args.index('--value') + 1]
            return issue['metadata']
        if command == 'status':
            issue = self.parent if args[0] == PARENT else self.child
            issue['status'] = args[1]
            self.assert_no_start(args)
            return issue
        if command == 'assign':
            self.child['assignee_id'] = args[args.index('--to-id') + 1]
            self.assert_no_start(args)
            return self.child
        if command == 'runs':
            return self.runs
        if command == 'rerun':
            self.started += 1
            self.runs.append({'agent_id': TECHLEAD, 'id': 'task-1'})
            return self.runs[-1]
        raise AssertionError((command, args))

    @staticmethod
    def assert_no_start(args):
        if '--no-start' not in args:
            raise AssertionError('status or assignment unexpectedly started an agent')


class QualityIncidentTests(unittest.TestCase):
    def dispatched_delivery(self, directory, cli):
        cli.parent['metadata'].update({
            'execution_gate': 'dispatched',
            'delivery_handoff': json.dumps({'stage': 'approved',
                'source_task': 'author-task', 'owner': TECHLEAD})})
        receipt = {'issue_id': PARENT, 'label': 'QATEST-1', 'merge_sha': SHA,
                   'head_sha': SHA, 'delivery': {'source_task': 'author-task',
                   'author': PARENT, 'reviewer': TECHLEAD,
                   'review_task': 'review-task', 'manifest_sha256': 'b' * 64}}
        folder = Path(directory) / 'release-receipts'
        folder.mkdir()
        path = folder / 'QATEST-1.json'
        path.write_text(json.dumps(receipt))
        return path, receipt

    def test_dispatched_delivery_transitions_with_exact_approved_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            self.dispatched_delivery(directory, cli)
            record(directory, cli, **self.kwargs(), budget_ready=True)
            record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(cli.parent['metadata']['execution_gate'], 'blocked_deployed_qa')
            self.assertEqual(cli.created, 1)
            self.assertEqual(cli.started, 1)

    def test_paused_route_projection_preserves_frozen_approved_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            cli=FakeCLI();self.dispatched_delivery(directory,cli)
            record(directory,cli,**self.kwargs(),budget_ready=False)
            cli.parent['metadata']['delivery_handoff']=json.dumps({
                'stage':'paused','source_task':None,'owner':TECHLEAD})
            with patch('portable_qa_gate_evidence.verify',side_effect=AssertionError('already frozen')):
                record(directory,cli,**self.kwargs(),budget_ready=False)
            self.assertEqual(cli.created,1)
            self.assertEqual(cli.started,0)
            cli.parent['metadata']['delivery_handoff']=json.dumps({
                'stage':'approved','source_task':'other-delivery','owner':TECHLEAD})
            with self.assertRaisesRegex(ValueError,'QA gate delivery'):
                record(directory,cli,**self.kwargs(),budget_ready=False)

    def test_legacy_paused_projection_requires_real_historical_verification(self):
        for valid in (False,True):
            with self.subTest(valid=valid),tempfile.TemporaryDirectory() as directory:
                cli=FakeCLI();_,delivery=self.dispatched_delivery(directory,cli)
                cli.parent['metadata'].update(execution_gate='blocked_deployed_qa',
                    delivery_handoff=json.dumps({'stage':'paused','source_task':None,'owner':TECHLEAD}))
                proof={'operation':'existing_approved_snapshot_verified_not_new_approval',
                       'issue_id':PARENT,'delivery':delivery['delivery'],'delivery_approval':not valid}
                with patch('portable_qa_gate_evidence.verify',return_value=proof) as verify:
                    if valid:record(directory,cli,**self.kwargs(),budget_ready=False)
                    else:
                        with self.assertRaisesRegex(ValueError,'historical verification drift'):
                            record(directory,cli,**self.kwargs(),budget_ready=False)
                    verify.assert_called_once()
                self.assertEqual(cli.started,0)

    def test_dispatched_gate_rejects_missing_stale_or_self_review_evidence(self):
        for defect in ('missing', 'sha', 'issue', 'source', 'reviewer', 'stage'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                cli = FakeCLI()
                path, receipt = self.dispatched_delivery(directory, cli)
                if defect == 'missing':
                    path.unlink()
                else:
                    if defect == 'sha': receipt['merge_sha'] = 'c' * 40
                    if defect == 'issue': receipt['issue_id'] = CHILD
                    if defect == 'source': receipt['delivery']['source_task'] = 'stale-task'
                    if defect == 'reviewer': receipt['delivery']['reviewer'] = PARENT
                    if defect == 'stage':
                        cli.parent['metadata']['delivery_handoff'] = json.dumps({
                            'stage': 'running', 'source_task': 'author-task', 'owner': TECHLEAD})
                    path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, 'QA gate'):
                    record(directory, cli, **self.kwargs(), budget_ready=True)
                self.assertEqual(cli.started, 0)
                self.assertEqual(cli.parent['metadata']['execution_gate'], 'dispatched')

    def test_unknown_parent_gate_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            cli.parent['metadata']['execution_gate'] = 'blocked_other_delivery'
            with self.assertRaisesRegex(ValueError, 'parent gate drift'):
                record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(cli.started, 0)

    def test_browser_failure_has_durable_owner_without_http_case_fiction(self):
        from test_portable_contract import contract
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            args = {**self.kwargs(), 'phase': 'browser',
                    'error': ValueError('post-deploy browser QA browser assertion failed'),
                    'parent_contract': contract()}
            first = record(directory, cli, **args, budget_ready=False)
            second = record(directory, cli, **args, budget_ready=False)
            self.assertEqual(first['phase'], 'browser')
            self.assertEqual(second['child_issue_id'], CHILD)
            self.assertEqual(cli.parent['metadata']['execution_gate'], 'blocked_browser_qa')
            self.assertEqual(cli.created, 1)
            self.assertEqual(cli.started, 0)

    def test_duplicate_urls_identify_exact_case_without_relaxing_checks(self):
        cases = [{'path': '/', 'status': 200, 'text_contains': ['<form']},
                 {'path': '/', 'status': 200, 'text_contains': ['feedback-summary']}]
        contract = {'qa_cases': cases}
        failure = qa_case_failure('post-deploy content mismatch', cases[1], contract)
        self.assertEqual(failing_case(contract, str(failure)), cases[1])
        with self.assertRaisesRegex(ValueError, 'one exact contract case'):
            failing_case(contract, 'post-deploy content mismatch: /')
        with self.assertRaisesRegex(ValueError, 'one exact contract case'):
            failing_case(contract, 'post-deploy content mismatch [qa-case=' + '0' * 64 + ']: /')

    def test_exact_qa_case_does_not_confuse_root_with_static_path(self):
        contract = {'qa_cases': [{'path': '/', 'status': 200},
                                 {'path': '/static/app.js', 'status': 200}]}
        case = failing_case(contract,
                            'post-deploy content type mismatch: /static/app.js')
        self.assertEqual(case['path'], '/static/app.js')

    def kwargs(self):
        return {'context': {'issue_id': PARENT}, 'label': 'QATEST-1',
                'phase': 'deployed', 'source_sha': SHA,
                'error': ValueError('post-deploy content type mismatch: /static/app.js'),
                'techlead_id': TECHLEAD}

    def test_budget_pause_restart_and_single_techlead_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            first = record(directory, cli, **self.kwargs(), budget_ready=False)
            self.assertEqual(first['dispatch'], 'budget_paused')
            self.assertEqual(cli.parent['status'], 'blocked')
            self.assertEqual(cli.child['assignee_id'], TECHLEAD)
            self.assertEqual(cli.started, 0)
            self.assertEqual(find(directory, PARENT, 'QATEST-1')['key'], first['key'])
            second = record(directory, cli, **self.kwargs(), budget_ready=False)
            self.assertEqual(second['child_issue_id'], CHILD)
            self.assertEqual(cli.created, 1)
            third = record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(third['dispatch'], 'techlead_started')
            self.assertEqual(cli.child['metadata']['execution_gate'], 'techlead_diagnosis')
            self.assertEqual(cli.started, 1)
            record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(cli.created, 1)
            self.assertEqual(cli.started, 1)

    def test_rejects_drift_and_non_qa_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            record(directory, cli, **self.kwargs(), budget_ready=False)
            with self.assertRaisesRegex(ValueError, 'identity drift'):
                record(directory, cli, **{**self.kwargs(), 'error': ValueError(
                    'post-deploy content mismatch: /static/app.js')}, budget_ready=False)
            with self.assertRaisesRegex(ValueError, 'not a contract'):
                record(directory, cli, **{**self.kwargs(), 'error': ValueError(
                    'Docker engine unavailable')}, budget_ready=False)

    def test_lost_dispatch_response_reconciles_existing_run(self):
        class LostResponse(FakeCLI):
            def __init__(self):
                super().__init__()
                self.fail_once = True

            def __call__(self, command, *args):
                result = super().__call__(command, *args)
                if command == 'rerun' and self.fail_once:
                    self.fail_once = False
                    raise OSError('response lost after queueing')
                return result

        with tempfile.TemporaryDirectory() as directory:
            cli = LostResponse()
            record(directory, cli, **self.kwargs(), budget_ready=False)
            with self.assertRaisesRegex(OSError, 'response lost'):
                record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(cli.started, 1)
            resumed = record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(resumed['dispatch'], 'techlead_started')
            self.assertEqual(cli.started, 1)
            self.assertEqual(cli.created, 1)

    def test_completed_parent_cannot_be_rewritten_as_qa_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            cli.parent['status'] = 'done'
            with self.assertRaisesRegex(ValueError, 'completed delivery'):
                record(directory, cli, **self.kwargs(), budget_ready=False)
            self.assertEqual(cli.created, 0)

    def test_controller_reports_quality_block_without_retry_loop(self):
        context = {'issue_id': PARENT}
        incident = {'child_issue_id': CHILD, 'phase': 'deployed',
                    'category': 'post-deploy content mismatch: /',
                    'dispatch': 'budget_paused'}
        with patch.object(portable_delivery, 'read_context', return_value=context), \
                patch.object(portable_delivery, 'reconcile',
                             side_effect=QualityBlocked(incident)) as reconcile, \
                patch.object(portable_delivery, 'status') as status:
            portable_delivery.run_controller({'test': True})
        reconcile.assert_called_once()
        self.assertEqual(status.call_args.args[:2], ('qa_blocked', context))

    def test_controller_restart_resumes_incident_before_old_approval(self):
        contract = {'test': True}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True,
                                 separators=(',', ':')).encode()).hexdigest()
        context = {'issue_id': PARENT, 'base_sha': SHA, 'contract_sha256': digest}
        incident = {'key': 'incident-key', 'phase': 'deployed', 'source_sha': SHA,
                    'category': 'post-deploy content type mismatch: /static/app.js',
                    'child_issue_id': CHILD, 'dispatch': 'budget_paused'}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'receipt.json'
            receipt.write_text(json.dumps({**context, 'contract_sha256': digest,
                                           'qa_incident': incident}))
            with patch.object(portable_delivery, 'RECEIPT', receipt), \
                    patch.object(portable_delivery, 'cli',
                                 return_value={'id': PARENT, 'status': 'blocked'}), \
                    patch.object(portable_delivery, 'quality_failure',
                                 return_value=incident) as escalate, \
                    patch.object(portable_delivery, 'approved') as approved:
                with self.assertRaises(QualityBlocked):
                    portable_delivery.reconcile(context, contract)
            escalate.assert_called_once()
            approved.assert_not_called()

    def test_cancelled_failed_parent_uses_recovery_without_reblocking(self):
        context = {'issue_id': PARENT, 'base_sha': SHA,
                   'contract_sha256': 'b' * 64}
        incident = {'key': 'incident-key', 'phase': 'deployed',
                    'source_sha': SHA, 'child_issue_id': CHILD,
                    'category': 'post-deploy content type mismatch: /static/app.js'}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'receipt.json'
            receipt.write_text(json.dumps({**context, 'qa_incident': incident}))
            def board(command, *args):
                if command == 'get':
                    return {'id': PARENT, 'status': 'cancelled'}
                if command == 'metadata':
                    return {'execution_gate': 'qa_recovered_by_child',
                            'qa_incident_issue_id': CHILD,
                            'qa_failed_source_sha': SHA}
                raise AssertionError(command)
            with patch.object(portable_delivery, 'RECEIPT', receipt), \
                    patch.object(portable_delivery, 'cli', side_effect=board), \
                    patch.object(portable_delivery, 'quality_failure') as record_again, \
                    patch.object(portable_delivery, 'approved') as approved:
                with self.assertRaises(QualityBlocked):
                    portable_delivery.reconcile(context, {'test': True})
            record_again.assert_not_called()
            approved.assert_not_called()


if __name__ == '__main__':
    unittest.main()
