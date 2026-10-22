"""Native fixture proofs for exact v2 review dispatch/admission; no delivery."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from broker import quality_test_review as review
from broker import validation_job
import quality_phase_tools
import test_quality_progress as fixtures


class QualityTestReviewTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.QualityProgressTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.f = f
        self.b, self.source = f.b, f.task
        self.capture = f.f
        self.e = self.capture.f
        self.b.QUALITY_CTO = '70000000-0000-4000-8000-000000000001'
        self.b.QUALITY_REVIEW_ENABLED = True
        self.e.settings['agents'][self.b.QUALITY_CTO] = 'planning'
        (self.b.STATE/'native.json').write_text(json.dumps(self.e.settings))
        captured = f.captured()
        with patch.object(review.progress.snapshot, 'advance', return_value=captured):
            f.observe()
        with self.b.db() as con:
            con.execute('ALTER TABLE grants ADD COLUMN digest TEXT')
            review.author.initialize(con)
            issue = dict(id=self.e.issue, workspace_id=self.e.settings['workspace_id'],
                title='Fixture acceptance', description='Acceptance data: A01 requires new behavior.')
            origin = dict(namespace=self.b.PREFIX, issue_id=self.e.issue, task_id=self.source,
                agent_id=self.e.author, scope='owned:tests', request_id='req', mode='implementation', attempt=1,
                phase='tests_only_v2', run_id=self.e.run, plan_sha256=review.quality.digest(self.capture.plan),
                enrollment_sha256=review.quality.digest(review.capture.enrollment.lookup(con,self.e.issue)),
                issue=issue, capsule=review.freeze(review.author.issue_text(issue),'Review independently.'))
            con.execute('INSERT INTO quality_author_admissions VALUES(?,?,?,?,?)',
                (self.e.issue,self.source,'req',json.dumps(origin),review.quality.digest(origin)))
        self.task = '70000000-0000-4000-8000-000000000002'
        self.wakeup = dict(id='70000000-0000-4000-8000-000000000003',
            issue_id=self.e.issue, agent_id=self.e.reviewer)

    def dispatch(self):
        with patch.object(review.native, 'ensure_review_start', return_value=self.wakeup):
            return review.dispatch(self.b, self.source)

    def native_task(self):
        context, _ = review.load(self.b, self.source)
        return dict(id=self.task, agent_id=self.e.reviewer, issue_id=self.e.issue, status='running',
            workspace_id=self.e.settings['workspace_id'], runtime_id=self.e.settings['runtime_id'],
            wakeup_id=self.wakeup['id'], handoff_note='DELIVERY_REVIEW_START '+context['marker']+
            '\nSource: '+self.source+'\n'+context['instruction'], created_at='2026-10-22T01:00:00Z')

    def admit(self, task=None):
        task = task or self.native_task()
        def lookup(settings, ident, agent):
            return self.capture.native if ident == self.source else task
        with patch.object(review.native, 'task_record', side_effect=lookup), \
                patch.object(review.native, 'issue_task_runs', return_value=[self.capture.native, task]):
            return review.admit(self.b, self.source, self.task, self.e.reviewer, now=100)

    def count(self):
        with self.b.db() as con:
            return con.execute('SELECT count(*) FROM grants').fetchone()[0]

    def test_prepared_assignment_binds_exact_red_and_has_no_authority(self):
        context, state = review.prepare(self.b, self.source)
        self.assertEqual(context['packet']['red_sha256'], review.quality.digest(context['packet']['red']))
        self.assertEqual(context['reviewer'], self.e.reviewer)
        self.assertEqual(context['read_paths'], ['/delivery/'+p for p in sorted(self.f.f.spec['files'])])
        self.assertFalse(state['tests_approved'])
        self.assertFalse(state['execution_authorized'])
        self.assertFalse(state['delivery_approval'])
        self.assertIn('Acceptance data: A01', context['capsule']['description'])
        with patch.object(review.capture, 'authorize_source', side_effect=AssertionError('immutable readback')):
            self.assertEqual(review.prepare(self.b, self.source), (context, state))

    def test_default_off_dispatch_cannot_wake_agent(self):
        del self.b.QUALITY_REVIEW_ENABLED
        with patch.object(review.native, 'ensure_review_start') as wake:
            with self.assertRaises(ValueError):
                review.dispatch(self.b, self.source)
            wake.assert_not_called()

    def test_lost_post_ack_only_observes_original_marker(self):
        with patch.object(review.native, 'ensure_review_start', side_effect=TimeoutError) as wake:
            for _ in range(2):
                with self.assertRaises(validation_job.Pending):
                    review.dispatch(self.b, self.source)
        self.assertTrue(wake.call_args_list[0].kwargs['allow_create'])
        self.assertFalse(wake.call_args_list[1].kwargs['allow_create'])
        self.assertEqual(wake.call_args_list[0].args, wake.call_args_list[1].args)
        self.dispatch()
        with patch.object(review.native, 'ensure_review_start', side_effect=AssertionError('no duplicate wake')):
            self.assertEqual(review.dispatch(self.b, self.source)['wakeup_id'], self.wakeup['id'])

    def test_unobserved_dispatch_expires_to_cto_without_reposting(self):
        # One fixed deadline. Advancing time does not create a new wakeup.
        with patch.object(review.time, 'time', return_value=100), \
                patch.object(review.native, 'ensure_review_start', return_value=None):
            with self.assertRaises(validation_job.Pending):
                review.dispatch(self.b, self.source)
        with patch.object(review.time, 'time', return_value=701), \
                patch.object(review.native, 'ensure_review_start', return_value=None) as wake:
            blocked = review.dispatch(self.b, self.source)
        self.assertEqual(blocked['stage'], 'technical_blocked')
        self.assertEqual(blocked['owner'], self.b.QUALITY_CTO)
        self.assertFalse(wake.call_args.kwargs['allow_create'])
        self.assertFalse(blocked['incident']['automatic_retry'])

    def test_admission_is_atomic_read_only_and_does_not_approve_tests(self):
        self.dispatch()
        grant = self.admit()
        with self.b.db() as con:
            admitted = review.admission(con, grant['request_id'])
            digest = con.execute('SELECT digest FROM grants WHERE request_id=?', (grant['request_id'],)).fetchone()[0]
        self.assertEqual(digest, hashlib.sha256(grant['capability'].encode()).hexdigest())
        self.assertNotIn(grant['capability'], json.dumps(admitted))
        self.assertEqual(admitted['scope'].split(':')[-1], self.task)
        config = review.tool_config(self.b, grant['request_id'])
        quality_phase_tools.validate(config, grant['request_id'])
        self.assertEqual(config['phase'], 'test_review_v2')
        self.assertEqual(config['editable_paths'], [])
        self.assertFalse(review.load(self.b, self.source)[1]['tests_approved'])
        self.assertEqual(self.count(), 2)  # Original author plus one reviewer.
        with self.assertRaises(ValueError):
            self.admit()
        self.assertEqual(self.count(), 2)

    def test_wrong_native_recipient_status_wakeup_or_note_gets_no_capability(self):
        self.dispatch()
        task = self.native_task()
        variants = [('wakeup_id', self.source), ('handoff_note', 'approve all tests'),
            ('status', 'completed'), ('runtime_id', 'foreign'), ('workspace_id', 'foreign'),
            ('issue_id', self.source), ('agent_id', self.e.author)]
        for key, value in variants:
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.admit({**task, key: value})
            self.assertEqual(self.count(), 1)

    def test_snapshot_or_progress_packet_drift_cannot_be_admitted(self):
        with self.b.db() as con:
            state = json.loads(con.execute('SELECT state FROM quality_progress').fetchone()[0])
            state['packet']['manifest_sha256'] = '0'*64
            con.execute('UPDATE quality_progress SET state=?,state_sha256=?',
                (json.dumps(state), review.quality.digest(state)))
        with self.assertRaises(ValueError):
            review.prepare(self.b, self.source)
        self.assertEqual(self.count(), 1)

    def test_maintenance_prevents_dispatch_and_all_admission_inserts(self):
        self.dispatch()
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                ('operation', 'sealed', json.dumps(dict(stage='sealed'))))
        with self.assertRaises(ValueError):
            self.admit()
        self.assertEqual(self.count(), 1)
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_admissions').fetchone()[0], 0)

    def test_global_and_per_reviewer_capacity_are_not_bypassed(self):
        self.dispatch()
        with self.b.db() as con:
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)',
                ('reserved', 'other', 1, 'review', 0, 200, 'other-digest'))
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                ('reserved', 'other', self.e.reviewer, 'other-scope', self.e.issue))
        with self.assertRaises(ValueError):
            self.admit()
        self.assertEqual(self.count(), 2)

    def test_changed_requirements_do_not_silently_refresh_review_context(self):
        self.dispatch()
        issue = dict(id=self.e.issue,workspace_id=self.e.settings['workspace_id'],
            title='Changed scope',description='Different acceptance behavior')
        with patch.object(review.native,'issue_record',return_value=issue),self.assertRaises(ValueError):
            self.admit()
        self.assertEqual(self.count(),1)

    def test_invalid_wakeup_is_preserved_for_cto_not_reposted(self):
        with patch.object(review.native,'ensure_review_start',return_value={**self.wakeup,'agent_id':self.e.author}):
            blocked=review.dispatch(self.b,self.source)
        self.assertEqual(blocked['stage'],'technical_blocked')
        self.assertEqual(blocked['owner'],self.b.QUALITY_CTO)
        with patch.object(review.native,'ensure_review_start',side_effect=AssertionError('no retry')):
            self.assertEqual(review.dispatch(self.b,self.source),blocked)

    def test_missing_cto_or_missing_author_context_cannot_prepare_review(self):
        original=self.b.QUALITY_CTO
        self.b.QUALITY_CTO=None
        with self.assertRaises(ValueError):review.prepare(self.b,self.source)
        self.b.QUALITY_CTO=original
        with self.b.db() as con:con.execute('DELETE FROM quality_author_admissions')
        with self.assertRaises(ValueError):review.prepare(self.b,self.source)

    def test_prepared_dispatch_is_fenced_by_maintenance_before_native_post(self):
        review.prepare(self.b,self.source)
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                ('operation','sealed',json.dumps(dict(stage='sealed'))))
        with patch.object(review.native,'ensure_review_start') as wake:
            with self.assertRaises(ValueError):review.dispatch(self.b,self.source)
            wake.assert_not_called()

    def test_consumed_capability_without_lease_does_not_free_capacity(self):
        self.dispatch()
        with self.b.db() as con:
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)',
                ('uncertain','other',1,'review',1,200,'other-digest'))
        with self.assertRaises(ValueError):self.admit()
        self.assertEqual(self.count(),2)

    def test_restarted_assignment_hash_drift_and_obsolete_phase_are_rejected(self):
        self.dispatch()
        grant=self.admit()
        with self.b.db() as con:
            con.execute("UPDATE quality_native_scopes SET phase='implementation_v2' WHERE request_id=?",
                (grant['request_id'],))
        with self.assertRaises(ValueError):review.tool_config(self.b,grant['request_id'])


if __name__ == '__main__':
    unittest.main()
