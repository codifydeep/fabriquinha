"""Offline automatic trace registration fixtures; not delivery evidence."""
import contextlib
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import failed_execution_evidence as evidence


class TraceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE leases(status TEXT)')
        @contextlib.contextmanager
        def db():
            with self.con:yield self.con
        self.b=SimpleNamespace(db=db)
        self.data=dict(source_task='author',artifact_diagnosis=True,validation_failure=dict(category='executed_test_failure'),decision=dict(action='escalate_cto'))
        self.row=dict(source_task='author',stage='technical_decision_required',data=json.dumps(self.data))

    def test_success_is_durable_and_deduplicated(self):
        with patch.object(evidence,'register_trace',return_value=dict(proof=dict(manifest_sha256='a'*64))) as run:
            self.assertTrue(evidence.reconcile_trace(self.b,self.row));self.assertTrue(evidence.reconcile_trace(self.b,self.row));run.assert_called_once()
        state=json.loads(self.con.execute('SELECT state FROM completed_trace_attempts').fetchone()[0]);self.assertEqual(state['stage'],'complete');self.assertFalse(state['delivery_approval'])

    def test_active_worker_defers_and_failure_stops_identical_replay(self):
        self.con.execute("INSERT INTO leases VALUES('running')")
        with patch.object(evidence,'register_trace',side_effect=ValueError('no anchors')) as run:
            self.assertTrue(evidence.reconcile_trace(self.b,self.row));run.assert_not_called()
            self.con.execute('DELETE FROM leases')
            self.assertTrue(evidence.reconcile_trace(self.b,self.row));self.assertTrue(evidence.reconcile_trace(self.b,self.row));run.assert_called_once()
        state=json.loads(self.con.execute('SELECT state FROM completed_trace_attempts').fetchone()[0]);self.assertEqual(state['stage'],'blocked')

    def test_unrelated_failed_or_lost_candidates_never_enter_completed_trace_path(self):
        with patch.object(evidence,'register_trace') as run:
            for change in (dict(assertion_trace_evidence={}),dict(failed_execution_diagnostic={}),dict(lost_execution_diagnostic={}),dict(artifact_diagnosis=False)):
                self.assertFalse(evidence.reconcile_trace(self.b,{**self.row,'data':json.dumps({**self.data,**change})}))
            self.assertFalse(evidence.reconcile_trace(self.b,{**self.row,'stage':'accepted'}));run.assert_not_called()

    def test_interrupted_intent_resumes_once_then_blocks(self):
        self.con.execute('CREATE TABLE completed_trace_attempts(source_task TEXT PRIMARY KEY,state TEXT)')
        self.con.execute('INSERT INTO completed_trace_attempts VALUES(?,?)',('author',json.dumps(dict(stage='intent',starts=1,delivery_approval=False))))
        with patch.object(evidence,'register_trace',return_value=dict(proof=dict(manifest_sha256='b'*64))) as run:
            self.assertTrue(evidence.reconcile_trace(self.b,self.row));run.assert_called_once()
        state=json.loads(self.con.execute('SELECT state FROM completed_trace_attempts').fetchone()[0]);self.assertEqual(state['starts'],2);self.assertEqual(state['stage'],'complete')
        self.con.execute('UPDATE completed_trace_attempts SET state=?',(json.dumps(dict(stage='intent',starts=2,delivery_approval=False)),))
        with patch.object(evidence,'register_trace') as run:
            self.assertTrue(evidence.reconcile_trace(self.b,self.row));self.assertTrue(evidence.reconcile_trace(self.b,self.row));run.assert_not_called()
        state=json.loads(self.con.execute('SELECT state FROM completed_trace_attempts').fetchone()[0]);self.assertEqual(state['stage'],'blocked');self.assertEqual(state['failure_category'],'InterruptedExperiment')

    def test_membership_upgrade_requires_prior_trace_and_deduplicates_separately(self):
        with patch.object(evidence,'register_trace',return_value=dict(proof=dict(manifest_sha256='c'*64))) as run:
            self.assertFalse(evidence.reconcile_trace(self.b,self.row,membership=True));run.assert_not_called()
            row={**self.row,'data':json.dumps({**self.data,'assertion_trace_evidence':{'proof':{}}})}
            self.assertTrue(evidence.reconcile_trace(self.b,row,membership=True));self.assertTrue(evidence.reconcile_trace(self.b,row,membership=True))
            run.assert_called_once_with(self.b,'author',membership=True)
            self.assertFalse(evidence.reconcile_trace(self.b,{**row,'data':json.dumps({**self.data,'assertion_trace_evidence':{},'membership_trace_evidence':{'proof':{}}})},membership=True))
        state=json.loads(self.con.execute('SELECT state FROM completed_membership_attempts_v2').fetchone()[0]);self.assertEqual(state['stage'],'complete');self.assertFalse(state['delivery_approval'])

    def test_resolved_enrichment_blocker_is_history_not_current_action(self):
        proof={'proof':{'manifest_sha256':'d'*64},'delivery_approval':False}
        blocker=dict(stage='blocked',starts=1,failure_category='ValueError',required_action='diagnose_fixed_trace_experiment_without_identical_retry')
        data=dict(membership_trace_evidence=proof,assertion_trace_evidence=proof,
                  trace_auto_failure=blocker,required_action=blocker['required_action'])
        resolved=evidence.clear_superseded_trace_blocker(data,proof)
        self.assertNotIn('trace_auto_failure',resolved);self.assertNotIn('required_action',resolved)
        self.assertEqual(resolved['prior_trace_auto_failure'],blocker)
        self.assertEqual(data['trace_auto_failure'],blocker)
        for changed in ({**data,'assertion_trace_evidence':{}},{**data,'required_action':'unrelated_security_blocker'}):
            result=evidence.clear_superseded_trace_blocker(changed,proof)
            self.assertEqual(result,changed)
