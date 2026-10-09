from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import json

import portable_delivery
from test_portable_contract import contract


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


class PortableDeliveryTests(unittest.TestCase):
    def test_approved_handoff_with_ambiguous_revision_escalates_instead_of_waiting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'portable-implementer.json').write_text(json.dumps({'agent_id':'author'}))
            managed=dict(route={'enabled':True},state={'stage':'approved'})
            with patch.object(portable_delivery,'PRIVATE',root), \
                    patch.object(portable_delivery,'RUN_SPEC',None), \
                    patch.object(portable_delivery,'LABEL','TEST-1'), \
                    patch.object(portable_delivery,'managed_handoff',return_value=managed), \
                    patch.object(portable_delivery,'cli',return_value=[]), \
                    patch.object(portable_delivery,'approved_submission',side_effect=ValueError('expected one approved exact revision')):
                with self.assertRaisesRegex(portable_delivery.RecoveryEscalation,'approved_revision_ambiguous'):
                    portable_delivery.approved(dict(issue_id='issue',durable_handoffs=True))
    def test_publication_auth_wait_never_recovers_or_redispatches_workers(self):
        context={'issue_id':'issue'}
        with patch.object(portable_delivery,'read_context',return_value=context), \
                patch.object(portable_delivery,'reconcile',side_effect=portable_delivery.WaitingPublicationAccess('github_auth_required')), \
                patch.object(portable_delivery,'recover_implementation_worker') as recover, \
                patch.object(portable_delivery,'status') as status:
            portable_delivery.run_controller({'schema_version':1})
        recover.assert_not_called()
        self.assertEqual(status.call_args.args[:2],('waiting_publication_access',context))
        self.assertEqual(status.call_args.kwargs['category'],'github_auth_required')

    def test_verified_host_transition_waits_only_for_thirty_seconds(self):
        details={'phase':'test_first','error':'host_restart_diagnosis_required',
            'host_restart_recovery':{'request':{'issue_id':'issue','source_task':'source'},
                'proof':{'baseline_unchanged':True},'author_retry_authorized':False}}
        managed={'route':{'test_first':True},'state':{'stage':'technical_decision_required',
            'source_task':'source','updated':100,'data':json.dumps(details)}}
        for now,exception in ((101,portable_delivery.WaitingApproval),(131,portable_delivery.RecoveryEscalation)):
            with patch.object(portable_delivery,'managed_handoff',return_value=managed),patch.object(portable_delivery.time,'time',return_value=now):
                with self.assertRaises(exception):portable_delivery.approved({'issue_id':'issue','durable_handoffs':True})

    def test_review_revalidation_adopts_only_same_delivery_with_durable_invalidation(self):
        old = {'source_task': 'source', 'review_task': 'old', 'manifest_sha256': 'a' * 64,
               'author': 'author', 'reviewer': 'reviewer', 'volume': 'frozen'}
        new = {**old, 'review_task': 'new'}
        witness = {'payload': {'source_task': 'source', 'review_task': 'old',
                              'manifest_sha256': 'a' * 64}, 'old_status': 'policy_invalidated',
                   'new_status': 'approved', 'new_source': 'source',
                   'new_manifest': 'a' * 64, 'new_reviewer': 'reviewer'}
        with patch.object(portable_delivery, 'command', return_value=json.dumps(witness)):
            self.assertEqual(portable_delivery.revalidated_delivery(old, new), old)
            for candidate in ({**new, 'source_task': 'other'}, {**new, 'manifest_sha256': 'b' * 64}):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    portable_delivery.revalidated_delivery(old, candidate)
        with patch.object(portable_delivery, 'command', return_value=json.dumps({**witness, 'old_status': 'approved'})):
            with self.assertRaisesRegex(ValueError, 'revalidation'):
                portable_delivery.revalidated_delivery(old, new)

    def test_blocked_test_review_escalates_during_live_poll_not_only_qa_recording(self):
        managed = {'route': {'enabled': True}, 'state': {
            'stage': 'test_revision_blocked', 'data': json.dumps({'reason': 'inspection_stalled'})}}
        with patch.object(portable_delivery, 'managed_handoff', return_value=managed):
            with self.assertRaisesRegex(portable_delivery.RecoveryEscalation, 'test_revision_blocked:inspection_stalled'):
                portable_delivery.approved({'issue_id': 'issue', 'durable_handoffs': True})
    def test_managed_handoff_read_preserves_transition_timestamp(self):
        response = {'route': {'enabled': True}, 'state': {
            'stage': 'technical_decision_required', 'updated': 100, 'data': '{}'}}
        with patch.object(portable_delivery, 'command', return_value=json.dumps(response)) as read:
            result = portable_delivery.managed_handoff({'issue_id': 'issue'})
        self.assertEqual(result['state']['updated'], 100)
        self.assertIn('SELECT stage,owner,data,updated', read.call_args.args[-2])

    def test_test_author_failure_waits_for_bounded_cto_transition_not_another_retry(self):
        managed = {'route': {'test_first': True},
                   'state': {'stage': 'technical_decision_required', 'updated': 100,
                             'data': json.dumps({'phase': 'test_first',
                                                'error': 'test_author_execution_failed'})}}
        with patch.object(portable_delivery, 'managed_handoff', return_value=managed), \
                patch.object(portable_delivery.time, 'time', return_value=101):
            with self.assertRaisesRegex(portable_delivery.WaitingApproval, 'CTO diagnosis transition'):
                portable_delivery.approved({'issue_id': 'issue', 'durable_handoffs': True})
        with patch.object(portable_delivery, 'managed_handoff', return_value=managed), \
                patch.object(portable_delivery.time, 'time', return_value=131):
            with self.assertRaises(portable_delivery.RecoveryEscalation):
                portable_delivery.approved({'issue_id': 'issue', 'durable_handoffs': True})

    def test_first_snapshot_rejection_waits_only_for_fresh_single_attempt_transition(self):
        managed = {'route': {'test_first': True, 'test_first_files': ['test_new.py'], 'author': 'author'},
                   'state': {'stage': 'technical_decision_required', 'updated': 100,
                             'data': json.dumps({'phase': 'test_first',
                                'error': 'ValueError:test-first test path mismatch', 'source_task': 'first'})}}
        runs = [{'id': 'first', 'agent_id': 'author', 'status': 'completed'}]
        with patch.object(portable_delivery, 'managed_handoff', return_value=managed), \
                patch.object(portable_delivery.time, 'time', return_value=101), \
                patch.object(portable_delivery, 'cli', return_value=runs):
            with self.assertRaisesRegex(portable_delivery.WaitingApproval, 'bounded broker'):
                portable_delivery.approved({'issue_id': 'issue', 'durable_handoffs': True})
        for age, attempts in ((31, runs), (1, runs + [dict(runs[0], id='second')])):
            with patch.object(portable_delivery, 'managed_handoff', return_value=managed), \
                    patch.object(portable_delivery.time, 'time', return_value=100 + age), \
                    patch.object(portable_delivery, 'cli', return_value=attempts):
                with self.assertRaises(portable_delivery.RecoveryEscalation):
                    portable_delivery.approved({'issue_id': 'issue', 'durable_handoffs': True})

    def test_rejected_red_waits_for_cto_tick_but_never_becomes_approval(self):
        managed = {'route': {'test_first': True},
                   'state': {'stage': 'technical_decision_required', 'updated': 100,
                             'data': json.dumps({'phase': 'test_first',
                                 'error': 'ValueError:Red must be an executed failing test suite'})}}
        for now, exception in ((101, portable_delivery.WaitingApproval),
                               (131, portable_delivery.RecoveryEscalation)):
            with patch.object(portable_delivery, 'managed_handoff', return_value=managed), \
                    patch.object(portable_delivery.time, 'time', return_value=now):
                with self.assertRaises(exception):
                    portable_delivery.approved({'issue_id': 'issue', 'durable_handoffs': True})

    def test_browser_gate_rejects_pending_and_approval_for_other_sha_before_any_write(self):
        receipt = {'merge_sha': 'a' * 40, 'pr_url': 'pr', 'main_ci_run': 'ci',
                   'deployment': {'url': 'local'}}
        for approval in ('pending_real_browser', 'passed:' + 'b' * 40):
            with self.subTest(approval=approval), patch.object(
                    portable_delivery, 'cli', return_value={'browser_acceptance': approval}) as client:
                with self.assertRaises(portable_delivery.WaitingBrowserAcceptance):
                    portable_delivery.publish_board({'issue_id': 'issue'}, receipt)
                client.assert_called_once_with('metadata', 'list', 'issue')

    def test_browser_wait_does_not_repeat_or_dispatch_worker(self):
        with patch.object(portable_delivery, 'from_environment', return_value={}), \
                patch.object(portable_delivery, 'read_context', return_value={'issue_id': 'issue'}), \
                patch.object(portable_delivery, 'reconcile', side_effect=portable_delivery.WaitingBrowserAcceptance()), \
                patch.object(portable_delivery, 'status') as status, \
                patch.object(portable_delivery, 'recover_implementation_worker') as recover:
            portable_delivery.run_controller()
        recover.assert_not_called()
        self.assertEqual(status.call_args.args[0], 'waiting_browser_acceptance')

    def test_browser_gate_accepts_only_attestation_for_delivered_sha(self):
        receipt = {'merge_sha': 'a' * 40, 'pr_url': 'pr', 'main_ci_run': 'ci',
                   'deployment': {'url': 'local'}}
        def cli(command, *args):
            if command == 'metadata' and args[0] == 'list':
                return {'browser_acceptance': 'passed:' + receipt['merge_sha']}
            if command == 'get':
                return {'status': 'todo'}
            return {}
        with patch.object(portable_delivery, 'cli', side_effect=cli) as client:
            result = portable_delivery.publish_board({'issue_id': 'issue'}, receipt)
        self.assertEqual(result['status'], 'done')
        self.assertIn(('status', 'issue', 'done', '--no-start'),
                      [call.args for call in client.call_args_list])

    def test_candidate_resolution_detaches_author_before_native_parent_wakeup(self):
        with patch.object(portable_delivery, 'cli', side_effect=[
                {'assignee_id': 'author'}, {}, {}, {'assignee_id': None}]) as client:
            portable_delivery.detach_completed_candidate_author(
                {'issue_id': 'parent'}, {'author': 'author'})
        self.assertEqual(client.call_args_list[2].args,
                         ('assign', 'parent', '--unassign'))
        with patch.object(portable_delivery, 'cli', return_value={'assignee_id': None}) as client:
            portable_delivery.detach_completed_candidate_author(
                {'issue_id': 'parent'}, {'author': 'author'})
        self.assertEqual(client.call_count, 1)

    def test_candidate_resolution_rejects_foreign_owner_and_failed_detachment(self):
        with patch.object(portable_delivery, 'cli', return_value={'assignee_id': 'other'}) as client:
            with self.assertRaisesRegex(ValueError, 'assignee drift'):
                portable_delivery.detach_completed_candidate_author(
                    {'issue_id': 'parent'}, {'author': 'author'})
        self.assertEqual(client.call_count, 1)
        with patch.object(portable_delivery, 'cli', side_effect=[
                {'assignee_id': 'author'}, {}, {}, {'assignee_id': 'author'}]):
            with self.assertRaisesRegex(ValueError, 'not confirmed'):
                portable_delivery.detach_completed_candidate_author(
                    {'issue_id': 'parent'}, {'author': 'author'})

    def test_candidate_restart_registers_pending_correction_and_waits_for_new_review(self):
        context = {'issue_id': 'issue', 'base_sha': 'a' * 40, 'contract_sha256': 'b' * 64}
        with tempfile.TemporaryDirectory() as directory:
            receipt_file = Path(directory) / 'receipt.json'
            payload = {'finding': 'Preserve tests and correct the failed QA case.'}
            receipt_file.write_text(json.dumps({**context,
                'qa_incident': {'phase': 'candidate', 'key': 'c' * 16},
                'candidate_recovery': {'status': 'starting', 'payload': payload,
                                       'original_delivery': {'source_task': 'old'}}}))
            with patch.object(portable_delivery, 'RECEIPT', receipt_file), \
                    patch.object(portable_delivery, 'broker_post') as register, \
                    patch.object(portable_delivery, 'approved', side_effect=portable_delivery.WaitingApproval('new review pending')):
                with self.assertRaises(portable_delivery.WaitingApproval):
                    portable_delivery.reconcile(context, {})
            register.assert_called_once_with('/v1/candidate-corrections', payload)
            self.assertEqual(json.loads(receipt_file.read_text())['candidate_recovery']['status'], 'awaiting_review')

    def test_completed_without_model_output_escalates_before_review(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            (private / 'portable-implementer.json').write_text(json.dumps({'agent_id': 'author'}))
            (private / 'portable-reviewer.json').write_text(json.dumps({'agent_id': 'reviewer'}))
            run = {'id': 'author-2', 'agent_id': 'author', 'status': 'completed',
                   'created_at': '2026-09-29T01:00:00Z',
                   'result': {'output': 'No visible answer was produced. output-token limit'}}
            with patch.object(portable_delivery, 'LABEL', 'PORT-6'), \
                    patch.object(portable_delivery, 'PRIVATE', private), \
                    patch.object(portable_delivery, 'cli', return_value=[run]), \
                    patch.object(portable_delivery, 'approved_submission') as approved:
                with self.assertRaisesRegex(portable_delivery.RecoveryEscalation,
                                            'implementation_model_output_limit'):
                    portable_delivery.approved({'issue_id': 'issue-1'})
            approved.assert_not_called()

    def test_model_limit_escalates_without_repeated_wait(self):
        context = {'issue_id': 'issue-1'}
        with patch.object(portable_delivery, 'from_environment', return_value={}), \
                patch.object(portable_delivery, 'read_context', return_value=context), \
                patch.object(portable_delivery, 'reconcile',
                             side_effect=portable_delivery.RecoveryEscalation(
                                 'implementation_model_output_limit')), \
                patch.object(portable_delivery, 'status') as status:
            portable_delivery.run_controller()
        self.assertEqual(status.call_args.args[:2], ('escalation_required', context))
        self.assertEqual(status.call_args.kwargs['category'],
                         'implementation_model_output_limit')

    def test_newer_author_failure_precedes_stale_reviewer_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            (private / 'portable-implementer.json').write_text(json.dumps({'agent_id': 'author'}))
            (private / 'portable-reviewer.json').write_text(json.dumps({'agent_id': 'reviewer'}))
            runs = [
                {'id': 'author-1', 'issue_id': 'issue-1', 'agent_id': 'author',
                 'status': 'completed', 'created_at': '2026-09-29T00:00:00Z'},
                {'id': 'review-1', 'issue_id': 'issue-1', 'agent_id': 'reviewer',
                 'status': 'failed', 'created_at': '2026-09-29T00:01:00Z'},
                {'id': 'author-2', 'issue_id': 'issue-1', 'agent_id': 'author',
                 'status': 'failed', 'created_at': '2026-09-29T00:02:00Z'},
            ]
            with patch.object(portable_delivery, 'LABEL', 'PORT-6'), \
                    patch.object(portable_delivery, 'PRIVATE', private), \
                    patch.object(portable_delivery, 'cli', side_effect=lambda command, *_:
                                 {'id': 'issue-1', 'status': 'todo'} if command == 'get' else runs), \
                    patch.object(portable_delivery, 'reconcile_worker', return_value='author_failure') as author, \
                    patch.object(portable_delivery, 'reconcile_reviewer') as reviewer:
                self.assertEqual(portable_delivery.recover_implementation_worker(
                    {'issue_id': 'issue-1'}), 'author_failure')
            author.assert_called_once()
            reviewer.assert_not_called()

    def test_failed_reviewer_dispatches_targeted_wakeup_not_implementer(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            (private / 'portable-implementer.json').write_text(json.dumps({'agent_id': 'author'}))
            (private / 'portable-reviewer.json').write_text(json.dumps({'agent_id': 'reviewer'}))
            issue_id = 'issue-1'
            runs = [
                {'id': 'author-1', 'issue_id': issue_id, 'agent_id': 'author',
                 'status': 'completed', 'created_at': '2026-09-29T00:00:00Z'},
                {'id': 'review-1', 'issue_id': issue_id, 'agent_id': 'reviewer',
                 'status': 'failed', 'failure_reason': 'agent_error.process_failure',
                 'created_at': '2026-09-29T00:01:00Z'},
            ]
            original = {'id': 'original', 'agent_id': 'reviewer',
                        'filter_agent_id': 'author', 'event_types': ['task.completed'],
                        'instruction': 'Review frozen snapshot and run all tests.'}
            def cli(command, *args):
                if command == 'get':
                    return {'id': issue_id, 'status': 'todo'}
                if command == 'runs':
                    return runs
                if args[:1] == ('list',):
                    return [original]
                if args[:1] == ('create',):
                    return {'id': 'retry-wakeup', 'issue_id': issue_id,
                            'agent_id': 'reviewer', 'filter_task_id': 'review-1',
                            'event_types': ['task.failed']}
                raise AssertionError((command, args))
            with patch.object(portable_delivery, 'LABEL', 'PORT-6'), \
                    patch.object(portable_delivery, 'PRIVATE', private), \
                    patch.object(portable_delivery, 'REVIEWER_RECOVERY', private / 'reviewer-recovery.json'), \
                    patch.object(portable_delivery, 'cli', side_effect=cli) as client:
                self.assertEqual(portable_delivery.recover_implementation_worker(
                    {'issue_id': issue_id}), 'recovery_queued')
            commands = [call.args[:2] for call in client.call_args_list]
            self.assertNotIn(('rerun', issue_id), commands)
            self.assertIn(('wakeup', 'create'), commands)

    def test_control_plane_failure_becomes_visible_escalation(self):
        context = {'issue_id': 'issue-1'}
        with patch.object(portable_delivery, 'from_environment', return_value={}), \
                patch.object(portable_delivery, 'read_context', return_value=context), \
                patch.object(portable_delivery, 'reconcile', side_effect=portable_delivery.WaitingApproval()), \
                patch.object(portable_delivery, 'recover_implementation_worker',
                             side_effect=OSError('runtime unavailable')) as recover, \
                patch.object(portable_delivery, 'status') as status, \
                patch.object(portable_delivery.time, 'sleep'):
            portable_delivery.run_controller()
        self.assertEqual(recover.call_count, 2)
        self.assertEqual(status.call_args.args[:2], ('escalation_required', context))
        self.assertIn('recovery_control_plane:OSError', status.call_args.kwargs['category'])

    def test_branch_only_contains_reviewed_editable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare, repo = root / 'origin.git', root / 'repo'
            subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
            subprocess.run(['git', 'init', '-b', 'main', str(repo)], check=True, capture_output=True)
            git(repo, 'config', 'user.name', 'Test')
            git(repo, 'config', 'user.email', 'test@example.org')
            git(repo, 'remote', 'add', 'origin', str(bare))
            (repo / 'tests').mkdir()
            for name, content in {'AGENTS.md': b'policy\n', 'app.py': b'def value(): return 1\n',
                                  'tests/test_old.py': b'def test_old(): pass\n'}.items():
                (repo / name).write_bytes(content)
            git(repo, 'add', '.')
            git(repo, 'commit', '-m', 'base')
            git(repo, 'push', '-u', 'origin', 'main')
            base = git(repo, 'rev-parse', 'main')
            files = {'AGENTS.md': b'policy\n', 'app.py': b'def value(): return 2\n',
                     'tests/test_old.py': b'def test_old(): pass\n',
                     'tests/test_new.py': b'def test_new(): pass\n'}
            with patch.object(portable_delivery, 'REPO', repo):
                first = portable_delivery.ensure_branch(base, files, contract())
                second = portable_delivery.ensure_branch(base, files, contract())
            self.assertEqual(first, second)
            self.assertEqual(git(repo, 'diff', '--name-only', base, first).splitlines(),
                             ['app.py', 'tests/test_new.py'])
            self.assertEqual(git(repo, 'rev-parse', 'main'), base)
            corrected = {**files, 'app.py': b'def value(): return 3\n'}
            with patch.object(portable_delivery, 'REPO', repo):
                amended = portable_delivery.ensure_branch(base, corrected, contract(), predecessor=first)
                resumed = portable_delivery.ensure_branch(base, corrected, contract(), predecessor=first)
                self.assertEqual(amended, resumed)
                self.assertEqual(git(repo, 'rev-parse', amended + '^'), first)
                self.assertEqual(git(repo, 'rev-parse', 'main'), base)
                self.assertEqual(git(repo, 'ls-remote', 'origin', 'refs/heads/' + portable_delivery.BRANCH).split()[0], amended)


if __name__ == '__main__':
    unittest.main()
