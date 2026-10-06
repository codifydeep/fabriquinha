import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from broker import qa_cleanup_handoff as handoff
from broker import qa_cleanup_observer as observer


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'state.sqlite'
        self.b = SimpleNamespace(db=self.db)
        self.config = dict(failed_execution={'request': dict(task_id='task', issue_id='parent', source_sha='a'*40)},
                           failed_execution_sha256='b'*64, failed_browser_sha256='c'*64)
        with self.db() as con:
            observer.initialize(con)
            con.execute('INSERT INTO qa_cleanup_observations VALUES(?,?,?,?)',
                ('task', json.dumps(self.config), json.dumps(dict(stage='blocked', owner='techlead', category='cleanup_no_progress')), 1e30))
        self.fx = SimpleNamespace(ready=Mock(return_value=True),
            issue=Mock(return_value=dict(id='issue', identifier='EVAL-test')),
            wake=Mock(return_value=dict(id='wake')), task=Mock(return_value=None))
    @contextlib.contextmanager
    def db(self):
        con = sqlite3.connect(self.path); con.row_factory = sqlite3.Row
        try:
            with con: yield con
        finally: con.close()
    def task(self, action='request_correction', agent=handoff.TECHLEAD):
        return dict(id='diagnostic', status='completed', agent_id=agent, issue_id='issue', wakeup_id='wake',
            result={'output': json.dumps(dict(action=action, reason='Inspect exact resource state; no deletion approval', optional_files=[]))})
    def test_native_dispatch_survives_restart_without_duplicate_wakeup(self):
        first = handoff.tick(self.b, effects=self.fx, now=1)
        self.assertEqual(first['stage'], 'awaiting_diagnostic')
        handoff.tick(self.b, effects=self.fx, now=10)
        self.fx.wake.assert_called_once(); self.fx.issue.assert_called_once()
        self.fx.task.return_value = self.task()
        result = handoff.tick(self.b, effects=self.fx, now=20)
        self.assertEqual(result['stage'], 'diagnostic_recorded')
        self.assertFalse(result['diagnostics'][0]['execution_authorized'])
        handoff.tick(self.b, effects=self.fx, now=100)
        self.fx.wake.assert_called_once()
    def test_techlead_can_escalate_once_but_cto_cannot_recurse(self):
        handoff.tick(self.b, effects=self.fx, now=1)
        self.fx.task.return_value = self.task('escalate_cto')
        first = handoff.tick(self.b, effects=self.fx, now=10)
        self.assertEqual(first['role'], 'cto')
        self.fx.task.return_value = self.task('escalate_cto', handoff.CTO)
        second = handoff.tick(self.b, effects=self.fx, now=20)
        self.assertEqual(second['stage'], 'technical_blocked')
        handoff.tick(self.b, effects=self.fx, now=100)
        self.assertEqual(self.fx.wake.call_count, 2)
    def test_stale_task_or_extra_execution_authority_is_rejected(self):
        state = dict(target=handoff.TECHLEAD, issue_id='issue', wakeup_id='wake')
        with self.assertRaises(ValueError): handoff.verdict({}, state, dict(self.task(), wakeup_id='old'))
        task = self.task(); task['result']['output'] = json.dumps(dict(action='run_command', reason='wrong', optional_files=[]))
        with self.assertRaises(ValueError): handoff.verdict({}, state, task)
    def test_native_control_plane_failure_is_bounded_and_budget_pause_creates_nothing(self):
        self.fx.ready.return_value = False
        handoff.tick(self.b, effects=self.fx, now=1); self.fx.issue.assert_not_called()
        self.fx.ready.return_value = True; self.fx.issue.side_effect = TimeoutError()
        handoff.tick(self.b, effects=self.fx, now=40)
        result = handoff.tick(self.b, effects=self.fx, now=80)
        self.assertEqual(result['stage'], 'technical_blocked')
        handoff.tick(self.b, effects=self.fx, now=120); self.assertEqual(self.fx.issue.call_count, 2)
    def test_cleanup_success_without_accepted_assessment_does_not_invent_continuation(self):
        with self.db() as con:
            con.execute('UPDATE qa_cleanup_observations SET state=?', (json.dumps(dict(stage='cleanup_absence_confirmed', owner='devops')),))
        self.assertIsNone(handoff.tick(self.b, effects=self.fx, now=1))
        self.fx.issue.assert_not_called()

    def test_techlead_deadline_moves_to_cto_without_respawning_techlead(self):
        handoff.tick(self.b, effects=self.fx, now=1)
        result = handoff.tick(self.b, effects=self.fx, now=1802)
        self.assertEqual(result['stage'], 'issue_intent'); self.assertEqual(result['target'], handoff.CTO)
        self.fx.wake.assert_called_once()

    def test_uncertain_wakeup_ack_retains_dispatch_intent_for_idempotent_lookup(self):
        self.fx.wake.side_effect = [TimeoutError(), dict(id='wake')]
        first = handoff.tick(self.b, effects=self.fx, now=1)
        self.assertEqual(first['stage'], 'dispatch_intent')
        second = handoff.tick(self.b, effects=self.fx, now=40)
        self.assertEqual(second['stage'], 'awaiting_diagnostic')
        self.fx.issue.assert_called_once()
        # Native ensure_planning_start reconciles the same marker; never a new
        # instruction/source/revision after an uncertain acknowledgment.
        self.assertEqual(self.fx.wake.call_args_list[0].args[0], self.fx.wake.call_args_list[1].args[0])

    def test_continuation_requires_matching_accepted_receipts_and_exact_dossier_hash(self):
        receipt = dict(source_sha='a'*40, failed_execution_receipt_sha256='b'*64,
                       failed_browser_receipt_sha256='c'*64, historical_tdd_red=False)
        dossier = dict(receipt, request_task='task', original_u3_historical_red_hold=True)
        accepted = dict(stage='evidence_assessment_accepted', receipt=dict(evidence_sha256=observer.digest(dossier)))
        with self.db() as con:
            con.execute('CREATE TABLE u3_qa_reconciliations(task_id TEXT,receipt TEXT)')
            con.execute('CREATE TABLE u3_deployment_assessments(config TEXT,state TEXT)')
            con.execute('INSERT INTO u3_qa_reconciliations VALUES(?,?)', ('task', json.dumps(receipt)))
            con.execute('INSERT INTO u3_deployment_assessments VALUES(?,?)', (json.dumps(dict(dossier=dossier)), json.dumps(accepted)))
            self.assertIsNotNone(handoff.accepted_continuation(con, self.config))
            accepted['receipt']['evidence_sha256'] = 'wrong'
            con.execute('UPDATE u3_deployment_assessments SET state=?', (json.dumps(accepted),))
            self.assertIsNone(handoff.accepted_continuation(con, self.config))
