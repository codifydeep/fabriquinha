"""Coordinator/native fixtures, not an installed autonomous delivery cycle."""
import json
import unittest
from unittest.mock import patch
from broker import quality_delivery_review_progress as progress,quality_team_progress as team
import test_quality_delivery_review_attestation as fixtures
from test_quality_team_progress import configured


class DeliveryProgressTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryAttestationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.request=f.c['implementation_request'];self.b.QUALITY_DELIVERY_REVISION_ENABLED=True

    def call(self):return progress.advance(self.b,self.request,self.b.QUALITY_TECHLEAD)

    def test_valid_review_waits_for_publication_never_homologates(self):
        result=self.call();self.assertEqual(result['stage'],'awaiting_publication')
        self.assertEqual(result['owner'],self.b.QUALITY_TECHLEAD);self.assertFalse(result['delivery_approval'])
        self.assertFalse(result['merge_authorized']);self.assertFalse(result['execution_authorized'])
        self.assertEqual(self.call(),result)

    def test_changes_dispatch_original_author_once_with_durable_handoff(self):
        finding=dict(criterion=self.f.assignment['plan']['criteria'][0],path='app.py',line=1,quote='VALUE=1',
            expected='A complete behavior',observed='Only a fixture constant')
        self.f.update(action='request_changes',findings=[finding])
        wakeup=dict(id='c0000000-0000-4000-8000-000000000001',issue_id=self.f.c['issue_id'],agent_id=self.f.assignment['author'])
        with patch.object(progress.review.native,'ensure_scope_author_start',return_value=wakeup) as wake:
            result=self.call();self.assertEqual(self.call(),result)
        wake.assert_called_once();self.assertEqual(result['stage'],'awaiting_product_revision_admission')
        self.assertEqual(result['owner'],self.f.assignment['author']);self.assertFalse(result['delivery_approval'])

    def test_original_running_review_waits_without_repeating_jobs_or_wakeups(self):
        self.f.native['status']='running'
        with patch.object(progress.validation.validation_job,'run',side_effect=AssertionError('do not rerun validation')),\
                patch.object(progress.review.native,'ensure_review_start') as wake:
            result=self.call();again=self.call()
        wake.assert_not_called();self.assertEqual(result['stage'],'waiting_final_review')
        self.assertEqual(again['stage'],result['stage'])

    def test_invalid_verdict_is_visible_cto_incident_without_another_review(self):
        self.f.update(action='request_changes',findings=[])
        with patch.object(progress.review.native,'ensure_review_start') as wake:result=self.call()
        wake.assert_not_called();self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['owner'],self.b.QUALITY_CTO);self.assertFalse(result['incident']['automatic_retry'])

    def test_fabricated_return_without_durable_attestation_cannot_advance(self):
        with patch.object(progress.attestation,'observe',return_value=dict(stage='delivery_reviewed')),self.assertRaises(ValueError):self.call()

    def test_maintenance_and_disabled_phase_cannot_dispatch(self):
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=False
        with patch.object(progress.review.native,'ensure_review_start') as wake,self.assertRaises(ValueError):self.call()
        wake.assert_not_called();self.b.QUALITY_DELIVERY_REVIEW_ENABLED=True
        with self.b.db() as con:con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operator','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(progress.review.validation_job.Pending):self.call()

    def test_team_checkpoint_is_active_only_with_new_explicit_flag(self):
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=False
        self.assertTrue(team.terminal(self.b,'awaiting_independent_delivery_review'))
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=True
        self.assertFalse(team.terminal(self.b,'awaiting_independent_delivery_review'))
        self.assertFalse(team.terminal(self.b,'awaiting_publication'))
        self.assertTrue(team.terminal(self.b,'technical_blocked'))

    def test_team_tick_reaches_exact_final_review_without_operator_step(self):
        configured(self.b)
        result=team.tick(self.b,limit=1)
        self.assertEqual(len(result['observed']),1)
        self.assertEqual(result['observed'][0]['stage'],'awaiting_publication')
        self.assertFalse(result['observed'][0]['delivery_approval'])


if __name__=='__main__':unittest.main()
