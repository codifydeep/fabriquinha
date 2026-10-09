import json
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import portable_supervisor
from portable_supervisor import meaningful_change, read_status, supervise


LABEL = 'QATEST-1'


class PortableSupervisorTests(unittest.TestCase):
    def test_worker_interruption_refresh_only_for_qualified_nonterminal_transition(self):
        status=dict(stage='escalation_required',issue_id='issue',category='technical_decision_required:author_execution_failed')
        receipt=dict(request=dict(issue_id='issue',source_task='source'),operation='pre_tool_worker_interruption_recovery_v1',
                     stage='qualified_cto_decision',probe_status='passed',author_retry_authorized=False,delivery_approval=False)
        managed=dict(route=dict(enabled=True,issue_id='issue'),state=dict(stage='diagnose_cto',source_task='source',
                     data=json.dumps(dict(worker_interruption_recovery=receipt))))
        self.assertTrue(portable_supervisor.stale_worker_interruption_blocker(status,managed))
        for stage in ('technical_decision_required','approved','test_first_blocked'):
            managed['state']['stage']=stage
            self.assertFalse(portable_supervisor.stale_worker_interruption_blocker(status,managed))
        managed['state']['stage']='diagnose_cto';receipt['delivery_approval']=True
        managed['state']['data']=json.dumps(dict(worker_interruption_recovery=receipt))
        self.assertFalse(portable_supervisor.stale_worker_interruption_blocker(status,managed))

    def test_diagnostic_replay_can_refresh_transition_but_not_terminal_verdict(self):
        status = dict(stage='escalation_required', issue_id='issue',
            category='technical_decision_required:recipient_execution_failed')
        receipt = dict(request=dict(issue_id='issue', source_task='source'),
            repair_kind='preserve_typed_failed_author_scope_v1',
            installed_source_sha='3b7e2e6a3391fd58b6913c4b6a81702ed8be1caed0f0de2cdac4edb9df2cbf89',
            author_retry_authorized=False, delivery_approval=False)
        managed = dict(route=dict(enabled=True, issue_id='issue'),
            state=dict(stage='diagnose_cto', source_task='source',
                data=json.dumps(dict(execution_diagnosis_contract_repair=receipt))))
        self.assertTrue(portable_supervisor.stale_execution_diagnosis_blocker(status, managed))
        for stage in ('technical_decision_required', 'approved', 'test_first_blocked'):
            managed['state']['stage'] = stage
            self.assertFalse(portable_supervisor.stale_execution_diagnosis_blocker(status, managed))
        managed['state']['stage'] = 'accepted'
        receipt['author_retry_authorized'] = True
        managed['state']['data'] = json.dumps(dict(execution_diagnosis_contract_repair=receipt))
        self.assertFalse(portable_supervisor.stale_execution_diagnosis_blocker(status, managed))

    def test_existing_supervisor_lock_is_busy_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'portable-supervisor';folder.mkdir()
            with (folder/(LABEL+'.lock')).open('a+') as holder:
                fcntl.flock(holder.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(portable_supervisor,'PRIVATE',root), \
                        patch.object(portable_supervisor,'maintenance_active',return_value=False), \
                        patch.object(portable_supervisor,'verify_instance',return_value=[]), \
                        patch.object(portable_supervisor,'from_environment',return_value={}), \
                        patch.object(portable_supervisor,'load_run_spec',return_value={'label':LABEL}), \
                        patch.object(portable_supervisor.sys,'argv',['portable_supervisor.py']), \
                        patch.object(portable_supervisor,'supervise') as run:
                    self.assertEqual(portable_supervisor.main(),75)
                    run.assert_not_called()

    def test_review_transport_refresh_requires_exact_revalidated_snapshot(self):
        check=portable_supervisor.stale_review_transport_blocker
        status=dict(stage='escalation_required',category='technical_decision_required:technical_replanning_required',issue_id='issue')
        receipt=dict(error='ValueError:handoff instruction too large',approval=False,author_restarted=False,manifest_sha256='a'*64)
        data=dict(review_transport_recovery=receipt,evidence=dict(manifest_sha256='a'*64),snapshot=dict(task_id='source'))
        managed=dict(route=dict(enabled=True,issue_id='issue'),state=dict(stage='awaiting_acceptance',source_task='source',data=json.dumps(data)))
        self.assertTrue(check(status,managed))
        for changed in (dict(approval=True),dict(author_restarted=True),dict(manifest_sha256='b'*64)):
            bad={**data,'review_transport_recovery':{**receipt,**changed}}
            managed['state']['data']=json.dumps(bad)
            self.assertFalse(check(status,managed))
        managed['state']['data']=json.dumps(data);managed['state']['stage']='technical_decision_required'
        self.assertFalse(check(status,managed))

    def test_host_error_refresh_requires_same_issue_durable_restart_receipt(self):
        from portable_supervisor import stale_restart_blocker
        status={'stage':'escalation_required','category':'CalledProcessError:docker','issue_id':'issue'}
        data={'host_restart_recovery':{'request':{'issue_id':'issue','source_task':'source'},
            'proof':{'baseline_unchanged':True},'author_retry_authorized':False,'delivery_approval':False}}
        managed={'route':{'enabled':True,'issue_id':'issue'},'state':{'stage':'technical_decision_required',
            'source_task':'source','data':json.dumps(data)}}
        self.assertTrue(stale_restart_blocker(status,managed))
        status['category']='test_revision_blocked:size'
        self.assertFalse(stale_restart_blocker(status,managed))
        status['category']='CalledProcessError:docker';managed['route']['issue_id']='other'
        self.assertFalse(stale_restart_blocker(status,managed))

    def test_size_blocker_refresh_requires_new_durable_cto_evidence(self):
        from portable_supervisor import stale_size_blocker
        status={'stage':'escalation_required','category':'test_revision_blocked:size','issue_id':'issue'}
        details={'source_task':'source','manifest_sha256':'hash',
                 'size_invalidation':{'stage':'inadmissible_snapshot_not_review_override',
                    'request':{'issue_id':'issue','source_task':'source','manifest_sha256':'hash'}},
                 'rejection_diagnosis':{'status':'revision_required','wakeup_id':'wake'}}
        managed={'route':{'enabled':True},'state':{'stage':'test_revision_required','data':json.dumps(details)}}
        self.assertTrue(stale_size_blocker(status,managed))
        managed['state']['stage']='test_revision_blocked'
        self.assertFalse(stale_size_blocker(status,managed))
        managed['state']['stage']='test_revision_required'
        details['size_invalidation']['request']['issue_id']='other'
        managed['state']['data']=json.dumps(details)
        self.assertFalse(stale_size_blocker(status,managed))

    def test_main_rejects_wrong_instance_before_contract_or_worker(self):
        with patch.object(portable_supervisor, 'verify_instance', return_value=True), \
                patch.object(portable_supervisor, 'from_environment') as contract:
            with self.assertRaisesRegex(ValueError, 'instance ports'):
                portable_supervisor.main()
        contract.assert_not_called()

    def test_maintenance_defers_before_contract_or_worker(self):
        with patch.object(portable_supervisor,'verify_instance',return_value=[]), \
                patch.object(portable_supervisor,'maintenance_active',return_value=True), \
                patch.object(portable_supervisor,'from_environment') as contract, \
                patch.object(portable_supervisor,'run_delivery') as run:
            self.assertEqual(portable_supervisor.main(),0)
        contract.assert_not_called();run.assert_not_called()

    def test_waits_for_budget_then_resumes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            ledger = Path(directory) / 'ledger.json'
            status.write_text(json.dumps({'label': LABEL, 'stage': 'budget_paused'}))
            attempts = []
            def budget():
                attempts.append('budget')
                if len(attempts) == 1:
                    raise ValueError('model budget too low')
            def run():
                attempts.append('run')
                status.write_text(json.dumps({'label': LABEL,
                                              'stage': 'qa_recovered_by_child'}))
                return 0
            result = supervise(status, ledger, LABEL, run, budget,
                               lambda _: attempts.append('sleep'))
            self.assertEqual(result['result'], 'completed')
            self.assertEqual(attempts, ['budget', 'sleep', 'budget', 'run'])
            self.assertEqual(read_status(ledger, LABEL)['unexpected_exits'], 0)

    def test_repeated_unexpected_exit_becomes_visible_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            ledger = Path(directory) / 'ledger.json'
            calls = []
            result = supervise(status, ledger, LABEL,
                               lambda: calls.append(1) or 73,
                               lambda: None, lambda _: None)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result['stage'], 'supervisor_escalation')
            self.assertEqual(read_status(ledger, LABEL)['unexpected_exits'], 2)
            again = supervise(status, ledger, LABEL,
                              lambda: calls.append(1) or 73,
                              lambda: None, lambda _: None)
            self.assertEqual(again['stage'], 'supervisor_escalation')
            self.assertEqual(len(calls), 2)

    def test_timestamp_only_refresh_does_not_hide_a_loop(self):
        self.assertFalse(meaningful_change(
            {'label': LABEL, 'stage': 'qa_blocked', 'updated_at': 1},
            {'label': LABEL, 'stage': 'qa_blocked', 'updated_at': 2}))
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            ledger = Path(directory) / 'ledger.json'
            status.write_text(json.dumps({'label': LABEL, 'stage': 'qa_blocked',
                                          'updated_at': 0}))
            calls = []
            def run():
                calls.append(1)
                status.write_text(json.dumps({'label': LABEL, 'stage': 'qa_blocked',
                                              'updated_at': len(calls)}))
                return 0
            result = supervise(status, ledger, LABEL, run,
                               lambda: None, lambda _: None)
            self.assertEqual(result['stage'], 'supervisor_escalation')
            self.assertEqual(len(calls), 2)

    def test_known_blocker_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            status.write_text(json.dumps({'label': LABEL,
                                          'stage': 'candidate_replan_required'}))
            result = supervise(status, Path(directory) / 'ledger.json', LABEL,
                               lambda: self.fail('must not rerun'),
                               lambda: None, lambda _: None)
            self.assertEqual(result['result'], 'visible_blocker')

    def test_old_success_receipt_is_reverified_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            status.write_text(json.dumps({'label': LABEL,
                                          'stage': 'qa_recovered_by_child'}))
            calls = []
            result = supervise(status, Path(directory) / 'ledger.json', LABEL,
                               lambda: calls.append(1) or 0,
                               lambda: None, lambda _: None)
            self.assertEqual(calls, [1])
            self.assertEqual(result['result'], 'completed')

    def test_locked_controller_is_not_counted_as_a_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            ledger = Path(directory) / 'ledger.json'
            exits = iter((75, 0))
            def run():
                code = next(exits)
                if code == 0:
                    status.write_text(json.dumps({'label': LABEL,
                                                  'stage': 'deployed_qa_passed'}))
                return code
            result = supervise(status, ledger, LABEL, run,
                               lambda: None, lambda _: None)
            self.assertEqual(result['result'], 'completed')
            self.assertEqual(read_status(ledger, LABEL)['unexpected_exits'], 0)

    def test_rejects_foreign_or_symlinked_status(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            status.write_text(json.dumps({'label': 'OTHER-1', 'stage': 'done'}))
            with self.assertRaisesRegex(ValueError, 'label drift'):
                read_status(status, LABEL)
            link = Path(directory) / 'link.json'
            link.symlink_to(status)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                read_status(link, LABEL)


if __name__ == '__main__':
    unittest.main()
