import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import portable_delivery
from portable_qa_repair import (DiagnosisRejected, derive, dispatch_repair, parse_diagnosis,
                                prepare_repair, resume_once)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / 'projects/pilot-feedback-board-c2.contract.json').read_text())
SPEC = json.loads((ROOT / 'projects/pilot-feedback-board-c2.run.json').read_text())
PARENT = '11111111-1111-4111-8111-111111111111'
CHILD = '22222222-2222-4222-8222-222222222222'
TECHLEAD = '33333333-3333-4333-8333-333333333333'
AUTHOR = '44444444-4444-4444-8444-444444444444'
SHA = 'a' * 40
INCIDENT = {'key': 'd34db33f12345678', 'phase': 'deployed', 'label': 'FB-2',
            'source_sha': SHA, 'parent_issue_id': PARENT, 'child_issue_id': CHILD,
            'techlead_id': TECHLEAD}
DIAGNOSIS = {'decision': 'repair', 'root_cause': 'wrong JavaScript MIME type',
             'editable_code_files': ['app/server.py'],
             'new_test_file': 'tests/test_static_mime.py',
             'acceptance': ['GET /static/app.js has JavaScript MIME type']}


class RepairTests(unittest.TestCase):
    def test_browser_repair_preserves_browser_gate_and_runtime(self):
        browser = {'scenario': 'feedback-board-filter-v1', 'browser_image': 'sha256:' + 'b' * 64}
        parent = {**SPEC, 'browser_qa': browser,
                  'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}}
        contract, spec = derive({**INCIDENT, 'phase': 'browser'}, CONTRACT, parent,
                                CONTRACT['files'], DIAGNOSIS)
        self.assertEqual(spec['browser_qa'], browser)
        self.assertEqual(spec['runtime_env'], parent['runtime_env'])
        self.assertEqual(contract['qa_cases'], CONTRACT['qa_cases'])
        self.assertTrue(set(CONTRACT['test_files']) <= set(contract['protected_files']))

    def test_browser_repair_without_a_fixed_browser_gate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'browser'):
            derive({**INCIDENT, 'phase': 'browser'}, CONTRACT, SPEC,
                   CONTRACT['files'], DIAGNOSIS)

    def test_derives_new_red_first_contract_without_weakening_baseline(self):
        contract, spec = derive(INCIDENT, CONTRACT, SPEC, CONTRACT['files'], DIAGNOSIS)
        self.assertEqual(contract['qa_cases'], CONTRACT['qa_cases'])
        self.assertEqual(contract['test_image'], CONTRACT['test_image'])
        self.assertEqual(contract['test_command'], CONTRACT['test_command'])
        self.assertEqual(set(contract['editable_files']),
                         {'app/server.py', 'tests/test_static_mime.py'})
        self.assertTrue(set(CONTRACT['test_files']) <= set(contract['protected_files']))
        self.assertIn('TESTS ONLY', spec['description'])
        self.assertEqual(spec['reviewer_registry'], SPEC['reviewer_registry'])

    def test_agent_cannot_expand_code_scope_or_reuse_test(self):
        for changed in ({'editable_code_files': ['Dockerfile.feedback-bootstrap']},
                        {'new_test_file': 'tests/test_board_ui.py'},
                        {'new_test_file': '../test_escape.py'},
                        {'new_test_file': 'notes/regression.txt'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse_diagnosis(json.dumps({**DIAGNOSIS, **changed}),
                                CONTRACT, CONTRACT['files'])

    def test_single_dot_slash_is_canonicalized_without_allowing_traversal(self):
        normalized = parse_diagnosis(json.dumps({
            **DIAGNOSIS, 'new_test_file': './test_new_css_mime.py'}),
            CONTRACT, CONTRACT['files'])
        self.assertEqual(normalized['new_test_file'], 'test_new_css_mime.py')
        for path in ('./../test_escape.py', '././test_escape.py',
                     '/tmp/test_escape.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                parse_diagnosis(json.dumps({**DIAGNOSIS,
                                            'new_test_file': path}),
                                CONTRACT, CONTRACT['files'])

    def test_blocked_diagnosis_and_candidate_do_not_dispatch(self):
        blocked = {**DIAGNOSIS, 'decision': 'blocked', 'editable_code_files': [],
                   'new_test_file': '', 'acceptance': []}
        parsed = parse_diagnosis(json.dumps(blocked), CONTRACT, CONTRACT['files'])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(prepare_repair(directory, INCIDENT, CONTRACT, SPEC,
                             CONTRACT['files'], parsed, 'task-1')['stage'],
                             'diagnosis_blocked')
        with self.assertRaisesRegex(ValueError, 'candidate QA repair'):
            derive({**INCIDENT, 'phase': 'candidate'}, CONTRACT, SPEC,
                   CONTRACT['files'], DIAGNOSIS)

    def test_rejects_discovery_or_policy_drift(self):
        with self.assertRaisesRegex(ValueError, 'baseline test'):
            derive(INCIDENT, CONTRACT, SPEC,
                   CONTRACT['files'] + ['tests/test_unlisted.py'], DIAGNOSIS)
        missing = [name for name in CONTRACT['files'] if name != 'AGENTS.md']
        with self.assertRaisesRegex(ValueError, 'protected files'):
            derive(INCIDENT, CONTRACT, SPEC, missing, DIAGNOSIS)

    def test_persistent_artifact_is_idempotent_and_budget_gates_start(self):
        with tempfile.TemporaryDirectory() as directory:
            first = prepare_repair(directory, INCIDENT, CONTRACT, SPEC,
                                   CONTRACT['files'], DIAGNOSIS, 'task-1')
            second = prepare_repair(directory, INCIDENT, CONTRACT, SPEC,
                                    CONTRACT['files'], DIAGNOSIS, 'task-1')
            self.assertEqual(first, second)
            with self.assertRaisesRegex(ValueError, 'artifact drift'):
                prepare_repair(directory, INCIDENT, CONTRACT, SPEC,
                               CONTRACT['files'], DIAGNOSIS, 'task-other')
            called = []
            with self.assertRaisesRegex(ValueError, 'budget'):
                dispatch_repair(first, verified_sha=lambda: SHA,
                                budget_check=lambda: (_ for _ in ()).throw(ValueError('budget')),
                                start=lambda _: called.append(1), port_available=lambda _: True)
            self.assertEqual(called, [])
            with self.assertRaisesRegex(ValueError, 'main moved'):
                dispatch_repair(first, verified_sha=lambda: 'b' * 40,
                                budget_check=lambda: None,
                                start=lambda _: called.append(1), port_available=lambda _: True)
            self.assertEqual(called, [])
            result = dispatch_repair(first, verified_sha=lambda: SHA,
                                     budget_check=lambda: None,
                                     start=lambda env: called.append(env),
                                     port_available=lambda _: True)
            self.assertEqual(result['stage'], 'repair_dispatched')
            self.assertEqual(called[0]['DELIVERY_KIT_TEST_FIRST'], '1')

    def test_resume_requires_exact_diagnosis_identity(self):
        child = {'id': CHILD, 'parent_issue_id': PARENT,
                 'assignee_id': TECHLEAD, 'status': 'todo'}
        def cli(command, *args):
            if command == 'get':
                return child
            if command == 'metadata':
                return {'qa_incident_key': INCIDENT['key'], 'qa_source_sha': SHA}
            if command == 'runs':
                return [{'id': 'task-1', 'agent_id': TECHLEAD,
                         'status': 'completed'}]
            raise AssertionError(command)
        with tempfile.TemporaryDirectory() as directory:
            project = {'repository': CONTRACT['repository'], 'checkout': directory}
            with patch('portable_qa_repair.subprocess.check_output',
                       return_value='\n'.join(CONTRACT['files'])):
                result = resume_once(
                    directory, INCIDENT, CONTRACT, SPEC, project, cli=cli,
                    verified_sha=lambda: SHA, budget_check=lambda: None,
                    output_reader=lambda *_: ('task-1', json.dumps(DIAGNOSIS)),
                    start=lambda _: None, port_available=lambda _: True)
            self.assertEqual(result['stage'], 'repair_dispatched')
            self.assertTrue((Path(directory) / 'qa-repairs' /
                             (INCIDENT['key'] + '.contract.json')).exists())
            with patch('portable_qa_repair.subprocess.check_output') as git:
                moved = resume_once(directory, INCIDENT, CONTRACT, SPEC, project,
                                    cli=cli, verified_sha=lambda: 'b' * 40,
                                    budget_check=lambda: None,
                                    output_reader=lambda *_: ('task-1', json.dumps(DIAGNOSIS)))
            self.assertEqual(moved['stage'], 'main_moved_replan_required')
            git.assert_not_called()

    def test_completed_task_with_todo_card_rejects_unsafe_proposal_immediately(self):
        child = {'id': CHILD, 'parent_issue_id': PARENT,
                 'assignee_id': TECHLEAD, 'status': 'todo'}
        def cli(command, *args):
            if command == 'get':
                return child
            if command == 'metadata':
                return {'qa_incident_key': INCIDENT['key'], 'qa_source_sha': SHA}
            if command == 'runs':
                return [{'id': 'task-1', 'agent_id': TECHLEAD,
                         'status': 'completed'}]
            raise AssertionError(command)
        with tempfile.TemporaryDirectory() as directory, \
                patch('portable_qa_repair.subprocess.check_output',
                      return_value='\n'.join(CONTRACT['files'])):
            bad = {**DIAGNOSIS, 'new_test_file': '../tests/test_bad.py'}
            with self.assertRaises(DiagnosisRejected) as rejected:
                resume_once(directory, INCIDENT, CONTRACT, SPEC,
                            {'repository': CONTRACT['repository'], 'checkout': directory},
                            cli=cli, verified_sha=lambda: SHA,
                            budget_check=lambda: None,
                            output_reader=lambda *_: ('task-1', json.dumps(bad)))
        self.assertEqual(rejected.exception.task_id, 'task-1')

    def test_restart_accepts_only_exact_successful_repair_as_main_advance(self):
        merged = 'b' * 40
        repair_issue_id = '55555555-5555-4555-8555-555555555555'
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            prepared = prepare_repair(directory, INCIDENT, CONTRACT, SPEC,
                                      CONTRACT['files'], DIAGNOSIS, 'task-1')
            (private / ('portable-context-' + prepared['label'] + '.json')).write_text(
                json.dumps({'label': prepared['label'], 'base_sha': SHA,
                            'issue_id': repair_issue_id,
                            'contract_sha256': prepared['contract_sha256'],
                            'run_spec_sha256': prepared['run_spec_sha256']}))
            (private / SPEC['implementer_registry']).write_text(
                json.dumps({'agent_id': AUTHOR}))
            receipts = private / 'release-receipts'
            receipts.mkdir()
            child_receipt = {'label': prepared['label'], 'base_sha': SHA,
                             'merge_sha': merged, 'stage': 'deployed_qa_passed'}
            (receipts / (prepared['label'] + '.json')).write_text(
                json.dumps(child_receipt))
            def cli(command, *args):
                if command == 'get':
                    if args[0] == CHILD:
                        return {'id': CHILD, 'parent_issue_id': PARENT,
                                'assignee_id': TECHLEAD, 'status': 'todo'}
                    return {'id': repair_issue_id, 'assignee_id': AUTHOR}
                if command == 'metadata':
                    return {'qa_incident_key': INCIDENT['key'],
                            'qa_source_sha': SHA}
                if command == 'runs':
                    return [{'id': 'task-1', 'agent_id': TECHLEAD,
                             'status': 'completed'}]
                raise AssertionError(command)
            with patch('portable_qa_repair.subprocess.check_output',
                       return_value='\n'.join(CONTRACT['files'])):
                result = resume_once(
                    directory, INCIDENT, CONTRACT, SPEC,
                    {'repository': CONTRACT['repository'], 'checkout': directory},
                    cli=cli, verified_sha=lambda: merged,
                    budget_check=lambda: self.fail('no new dispatch'),
                    output_reader=lambda *_: ('task-1', json.dumps(DIAGNOSIS)),
                    start=lambda _: self.fail('must not start a duplicate'))
            self.assertEqual(result['stage'], 'repair_dispatched')
            self.assertTrue(result['resumed'])
            child_receipt['merge_sha'] = 'c' * 40
            (receipts / (prepared['label'] + '.json')).write_text(
                json.dumps(child_receipt))
            result = resume_once(
                directory, INCIDENT, CONTRACT, SPEC,
                {'repository': CONTRACT['repository'], 'checkout': directory},
                cli=cli, verified_sha=lambda: merged,
                budget_check=lambda: None,
                output_reader=lambda *_: ('task-1', json.dumps(DIAGNOSIS)))
            self.assertEqual(result['stage'], 'main_moved_replan_required')

    def test_controller_hands_completed_diagnosis_to_repair_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'parent.json'
            receipt.write_text('{}')
            with patch.object(portable_delivery, 'RUN_SPEC', {**SPEC, 'sha256': 'a' * 64}), \
                    patch.object(portable_delivery, 'RECEIPT', receipt), \
                    patch.object(portable_delivery, 'PRIVATE', Path(directory)), \
                    patch.object(portable_delivery, 'resume_qa_repair',
                                 return_value={'stage': 'repair_dispatched',
                                               'label': 'QAD34DB33F-1'}) as resume, \
                    patch.object(portable_delivery.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess([], 0)) as run:
                result = portable_delivery.drive_qa_repair(
                    {**INCIDENT, 'dispatch': 'techlead_started'}, CONTRACT)
            self.assertEqual(result['stage'], 'repair_incomplete')
            resume.assert_called_once()
            env = run.call_args.kwargs['env']
            self.assertEqual(env['DELIVERY_KIT_TEST_FIRST'], '1')
            self.assertTrue(env['DELIVERY_KIT_RUN_SPEC'].endswith(
                INCIDENT['key'] + '.run.json'))

    def test_stale_child_receipt_cannot_mask_failed_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            parent = private / 'parent.json'
            parent.write_text('{}')
            statuses = private / 'autonomy-status'
            statuses.mkdir()
            (statuses / 'QAD34DB33F-1.json').write_text(json.dumps({
                'label': 'QAD34DB33F-1', 'stage': 'escalation_required'}))
            receipts = private / 'release-receipts'
            receipts.mkdir()
            (receipts / 'QAD34DB33F-1.json').write_text(json.dumps({
                'label': 'QAD34DB33F-1', 'stage': 'deployed_qa_passed',
                'base_sha': SHA, 'merge_sha': 'b' * 40}))
            with patch.object(portable_delivery, 'RUN_SPEC', {**SPEC, 'sha256': 'a' * 64}), \
                    patch.object(portable_delivery, 'RECEIPT', parent), \
                    patch.object(portable_delivery, 'PRIVATE', private), \
                    patch.object(portable_delivery, 'resume_qa_repair',
                                 return_value={'stage': 'repair_dispatched',
                                               'label': 'QAD34DB33F-1'}), \
                    patch.object(portable_delivery.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess([], 0)):
                result = portable_delivery.drive_qa_repair(
                    {**INCIDENT, 'dispatch': 'techlead_started'}, CONTRACT)
            self.assertEqual(result['stage'], 'repair_incomplete')
            self.assertEqual(result['child_stage'], 'escalation_required')

    def test_rejected_techlead_retry_routes_once_to_cto(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            (private / 'planning-agents.json').write_text(json.dumps({
                'agents': {'cto': 'cto-agent'}}))
            parent = private / 'parent.json'
            parent.write_text('{}')
            retry = {'child_issue_id': 'retry-issue', 'dispatch': 'techlead_started',
                     'rejected_task_id': 'task-1', 'rejection_reason': 'unsafe'}
            cto = {'child_issue_id': 'cto-issue', 'dispatch': 'cto_started',
                   'cto_id': 'cto-agent', 'reason': 'Second Tech Lead diagnosis rejected: unsafe'}
            with patch.object(portable_delivery, 'RUN_SPEC', {**SPEC, 'sha256': 'a' * 64}), \
                    patch.object(portable_delivery, 'PRIVATE', private), \
                    patch.object(portable_delivery, 'RECEIPT', parent), \
                    patch.object(portable_delivery, 'find_qa_diagnosis_retry', return_value=retry), \
                    patch.object(portable_delivery, 'record_qa_diagnosis_retry', return_value=retry), \
                    patch.object(portable_delivery, 'find_qa_cto_escalation',
                                 side_effect=[None, cto]), \
                    patch.object(portable_delivery, 'record_qa_cto_escalation',
                                 return_value=cto) as escalate, \
                    patch.object(portable_delivery, 'resume_qa_repair',
                                 side_effect=[DiagnosisRejected('unsafe', task_id='task-2'),
                                              {'stage': 'diagnosis_blocked',
                                               'reason': 'no safe local fix'}]) as resume, \
                    patch('start_eval.check_model_budget', return_value={'remaining': 100}):
                result = portable_delivery.drive_qa_repair(
                    {**INCIDENT, 'dispatch': 'techlead_started'}, CONTRACT)
            self.assertEqual(result['stage'], 'cto_diagnosis_blocked')
            self.assertEqual(escalate.call_count, 2)
            self.assertEqual(resume.call_args.kwargs['diagnosis_agent_id'], 'cto-agent')
            self.assertEqual(resume.call_args.kwargs['diagnosis_issue_id'], 'cto-issue')

    def test_trigger_trial_stops_after_real_cto_dispatch_without_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            (private / 'planning-agents.json').write_text(json.dumps({
                'agents': {'cto': 'cto-agent'}}))
            parent = private / 'parent.json'
            parent.write_text('{}')
            retry = {'child_issue_id': 'retry-issue', 'dispatch': 'techlead_started',
                     'rejected_task_id': 'task-1', 'rejection_reason': 'unsafe'}
            cto = {'child_issue_id': 'cto-issue', 'dispatch': 'cto_started',
                   'cto_id': 'cto-agent',
                   'reason': 'Second Tech Lead diagnosis rejected: unsafe'}
            with patch.object(portable_delivery, 'RUN_SPEC', {**SPEC, 'sha256': 'a' * 64}), \
                    patch.object(portable_delivery, 'PRIVATE', private), \
                    patch.object(portable_delivery, 'RECEIPT', parent), \
                    patch.object(portable_delivery, 'find_qa_diagnosis_retry', return_value=retry), \
                    patch.object(portable_delivery, 'record_qa_diagnosis_retry', return_value=retry), \
                    patch.object(portable_delivery, 'find_qa_cto_escalation',
                                 side_effect=[None, cto]), \
                    patch.object(portable_delivery, 'record_qa_cto_escalation',
                                 return_value=cto), \
                    patch.object(portable_delivery, 'resume_qa_repair',
                                 side_effect=DiagnosisRejected('unsafe', task_id='task-2')) as resume, \
                    patch('start_eval.check_model_budget', return_value={'remaining': 100}):
                result = portable_delivery.drive_qa_repair(
                    {**INCIDENT, 'dispatch': 'techlead_started'}, CONTRACT,
                    stop_after_cto_dispatch=True)
            self.assertEqual(result, {'stage': 'cto_handoff_observed',
                                      'cto_issue_id': 'cto-issue'})
            resume.assert_called_once()

    def test_controller_records_repair_escalation_without_false_success(self):
        context = {'issue_id': PARENT}
        incident = {**INCIDENT, 'category': 'post-deploy bad MIME',
                    'dispatch': 'techlead_started'}
        from portable_qa_incident import QualityBlocked
        with patch.object(portable_delivery, 'RUN_SPEC', {**SPEC, 'sha256': 'a' * 64}), \
                patch.object(portable_delivery, 'configure_run'), \
                patch.object(portable_delivery, 'read_context', return_value=context), \
                patch.object(portable_delivery, 'reconcile',
                             side_effect=QualityBlocked(incident)), \
                patch.object(portable_delivery, 'drive_qa_repair',
                             side_effect=ValueError('diagnosis drift')), \
                patch.object(portable_delivery, 'status') as status:
            portable_delivery.run_controller(CONTRACT)
        self.assertEqual(status.call_args.args[:2], ('qa_repair_escalation', context))


if __name__ == '__main__':
    unittest.main()
