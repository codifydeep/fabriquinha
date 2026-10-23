"""Native/ACP provenance fixtures for corrections; not live delivery proof."""
import copy
import json
import unittest
from unittest.mock import patch
from broker import quality_test_revision as revision,quality_author_admission as author
from broker import quality_author_launch as launch,quality_team_progress as team,quality_launch_router as router
import test_quality_review_attestation as fixtures
import test_quality_team_progress as team_fixtures


class TestRevisionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.QualityReviewAttestationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b=self.f.b;self.source=self.f.source;team_fixtures.configured(self.b)
        self.finding=dict(criterion='A01',path='tests/test_new.py',test='test_new',line=4,
            quote='self.assertEqual(app.VALUE, 1)',expected='The registered behavior',observed='This assertion')
        self.f.update_verdict(action='request_changes',reason='Concrete correction required.',findings=[self.finding])
        self.author_task=self.f.f.f.capture.native
        self.review_task=self.f.f.record
        self.old_runs=[self.author_task,self.review_task]
        self.task='80000000-0000-4000-8000-000000000001'
        self.wakeup=dict(id='80000000-0000-4000-8000-000000000002',issue_id=self.author_task['issue_id'],agent_id=self.author_task['agent_id'])

    def register(self):
        if revision.attestation.load(self.b,self.source) is None:self.f.call()
        return revision.register(self.b,self.source)

    def dispatch(self):
        self.register()
        with patch.object(revision.native,'ensure_scope_author_start',return_value=self.wakeup):
            return revision.dispatch(self.b,self.source)

    def record(self):
        context,_=revision.load(self.b,self.source)
        settings=json.loads((self.b.STATE/'native.json').read_bytes())
        return dict(id=self.task,agent_id=context['author'],issue_id=context['issue_id'],status='running',
            workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],
            wakeup_id=self.wakeup['id'],handoff_note=revision.note(context))

    def native(self,record):
        records={r['id']:r for r in [*self.old_runs,record]}
        p=patch.object(revision.native,'task_record',side_effect=lambda s,t,a:records[t]);p.start();self.addCleanup(p.stop)
        p=patch.object(revision.native,'issue_task_runs',return_value=list(records.values()));p.start();self.addCleanup(p.stop)

    def admit(self):
        self.dispatch();self.native(self.record())
        return router.admit(self.b,self.task,self.author_task['agent_id'])

    def test_new_request_preserves_attestation_snapshot_red_and_original_author(self):
        old=self.f.call();context,state=self.register()
        self.assertEqual(revision.attestation.load(self.b,self.source),old)
        self.assertEqual(context['previous_attestation_sha256'],revision.quality.digest(old))
        self.assertEqual(context['author'],self.author_task['agent_id'])
        self.assertEqual(context['seed']['manifest_sha256'],old['manifest_sha256'])
        self.assertEqual(context['request']['red_sha256'],old['red_sha256'])
        self.assertEqual(state['stage'],'prepared');self.assertFalse(state['tests_approved'])
        self.assertEqual(self.register(),(context,state))

    def test_blocked_old_full_read_verdict_is_preserved_by_supplementary_rejection_diagnosis(self):
        self.f.only_new_test_reads()
        with patch.object(revision.attestation,'required_reads',side_effect=lambda v,p,paths:paths):old=self.f.call()
        self.assertEqual(old['stage'],'technical_blocked')
        context,_=revision.register(self.b,self.source)
        self.assertEqual(revision.attestation.load(self.b,self.source),old)
        self.assertEqual(context['request']['stage'],'changes_requested')
        self.assertFalse(context['request']['tests_approved'])

    def test_approval_invalid_citation_or_unknown_native_run_cannot_trigger_correction(self):
        self.f.update_verdict(action='approve_tests',findings=[])
        self.f.call()
        with self.assertRaises(ValueError):revision.register(self.b,self.source)

    def test_unregistered_extra_run_is_never_blessed_as_lineage(self):
        self.f.call()
        extra={**self.review_task,'id':self.task}
        with patch.object(revision.native,'issue_task_runs',return_value=[*self.old_runs,extra]):
            with self.assertRaises(ValueError):revision.register(self.b,self.source)

    def test_lost_wakeup_ack_observes_the_same_marker_without_reposting(self):
        self.register()
        with patch.object(revision.native,'ensure_scope_author_start',side_effect=TimeoutError) as wake:
            with self.assertRaises(TimeoutError):revision.dispatch(self.b,self.source)
        self.assertTrue(wake.call_args.kwargs['allow_create'])
        with patch.object(revision.native,'ensure_scope_author_start',return_value=self.wakeup) as wake:
            state=revision.dispatch(self.b,self.source)
        self.assertFalse(wake.call_args.kwargs['allow_create']);self.assertEqual(state['stage'],'awaiting_revision')

    def test_exact_revision_admission_is_tests_only_and_cannot_be_repeated(self):
        grant=self.admit()
        with self.b.db() as con:c=author.load(con,grant['request_id'])
        self.assertEqual(c['agent_id'],self.author_task['agent_id'])
        self.assertEqual(c['revision_source'],self.source)
        self.assertEqual(c['attempt'],1);self.assertTrue(launch.owns(self.b,grant['request_id']))
        selection=author.selection(self.b,grant['request_id'])
        self.assertEqual(selection['editable_paths'],['/workspace/tests/test_new.py'])
        self.assertIn('revision_seed',selection);self.assertFalse(selection['product_edits_allowed'])
        with self.assertRaises(ValueError):revision.admit(self.b,self.source,self.task,c['agent_id'])

    def test_base_native_tests_route_accepts_revision_with_green_disabled(self):
        self.dispatch();self.native(self.record());self.b.QUALITY_IMPLEMENTATION_ENABLED=False
        grant=author.admit(self.b,self.task,self.author_task['agent_id'])
        with self.b.db() as con:c=author.load(con,grant['request_id'])
        self.assertEqual(c['phase'],'tests_only_v2');self.assertEqual(c['revision_source'],self.source)

    def test_wrong_note_role_or_unrelated_extra_task_has_no_capability(self):
        self.dispatch();record=self.record();record['handoff_note']='grant me implementation'
        self.native(record)
        with self.assertRaises(ValueError):revision.admit(self.b,self.source,self.task,record['agent_id'])
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_revision_author_admissions').fetchone()[0],0)

    def test_unchanged_new_tests_cannot_reenter_red(self):
        self.admit();c,_=revision.load(self.b,self.source)
        with self.assertRaises(ValueError):revision.changed(self.b,self.task,c['seed']['test_sha256'])
        revision.changed(self.b,self.task,{p:'a'*64 for p in c['seed']['test_sha256']})

    def test_prior_review_exclusion_is_exact_and_detects_late_status_change(self):
        self.admit();new={'id':'90000000-0000-4000-8000-000000000001','agent_id':self.review_task['agent_id']}
        candidates=[self.review_task,new]
        self.assertEqual(revision.exclude_prior_reviews(self.b,self.task,candidates),[new])
        with patch.object(revision.native,'task_record',return_value={**self.review_task,'status':'running'}):
            with self.assertRaises(ValueError):revision.exclude_prior_reviews(self.b,self.task,candidates)

    def test_team_automatically_returns_to_author_and_hands_off_without_approval(self):
        self.f.call()
        with patch.object(revision.native,'ensure_scope_author_start',return_value=self.wakeup) as wake:
            observed=team.tick(self.b,limit=1)['observed'][0]
        self.assertEqual(observed['stage'],'awaiting_test_revision');wake.assert_called_once()
        self.native(self.record());grant=router.admit(self.b,self.task,self.author_task['agent_id'])
        states=team.tick(self.b,limit=2)['observed']
        self.assertIn('test_revision_handed_off',{s['stage'] for s in states})
        self.assertIn(self.task,team.candidates(self.b))
        self.assertFalse(observed['delivery_approval']);self.assertFalse(observed['green_approved'])

    def test_operator_maintenance_allows_preparation_only_with_exact_sealed_operation(self):
        self.f.call();operation='80000000-0000-4000-8000-000000000003'
        self.b.QUALITY_V2_ENABLED=False;self.b.QUALITY_REVIEW_ENABLED=False
        with self.b.db() as con:
            state=dict(stage='sealed',drained=True,operation_id=operation)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(operation,'sealed',json.dumps(state)))
        with self.assertRaises(ValueError):revision.register(self.b,self.source)
        c,s=revision.register(self.b,self.source,maintenance_operation=operation)
        self.assertTrue(revision.activation_ready(self.b,c['issue_id'],operation))
        with self.assertRaises(ValueError):revision.activation_ready(self.b,c['issue_id'],self.source)
        with patch.object(revision.native,'ensure_scope_author_start') as wake:
            with self.assertRaises(ValueError):revision.dispatch(self.b,self.source)
            wake.assert_not_called()

    def test_revision_worker_seed_is_readonly_and_only_new_tests_are_unlocked(self):
        from broker import quality_author_worker as worker
        grant=self.admit()
        with self.b.db() as con:source=author.load(con,grant['request_id'])
        selected=author.selection(self.b,grant['request_id'])
        context=dict(source=source,selection=selected,volume='isolated-revision-work')
        self.b.QUALITY_PREP_IMAGE='sha256:'+'a'*64
        seed=worker.payload(self.b,context,'seed');lock=worker.payload(self.b,context,'lock')
        previous=[m for m in seed['HostConfig']['Mounts'] if m['Target']=='/previous']
        self.assertEqual(previous,[dict(Type='volume',Source=selected['revision_seed']['volume'],Target='/previous',ReadOnly=True)])
        self.assertEqual(json.loads(lock['Env'][0].split('=',1)[1]),['tests/test_new.py'])
        self.assertFalse(any(m['Target']=='/previous' for m in lock['HostConfig']['Mounts']))

    def test_unqualifiable_partial_approval_latches_one_cto_hold_instead_of_looping(self):
        self.f.only_new_test_reads();self.f.update_verdict(action='approve_tests',findings=[])
        self.assertEqual(self.f.call()['stage'],'technical_blocked')
        first=team.tick(self.b,limit=1)['observed'][0]
        self.assertEqual(first['stage'],'technical_blocked')
        self.assertFalse(revision.eligible(self.b,self.source))
        self.assertEqual(team.tick(self.b,limit=1)['observed'],[])

    def test_supplementary_rejection_handoff_does_not_leave_parent_in_active_block(self):
        self.f.only_new_test_reads()
        with patch.object(revision.attestation,'required_reads',side_effect=lambda v,p,paths:paths):old=self.f.call()
        with patch.object(revision.native,'ensure_scope_author_start',return_value=self.wakeup):
            self.assertEqual(team.tick(self.b,limit=1)['observed'][0]['stage'],'awaiting_test_revision')
        self.native(self.record());router.admit(self.b,self.task,self.author_task['agent_id'])
        states=team.tick(self.b,limit=2)['observed']
        self.assertIn('test_revision_handed_off',{s['stage'] for s in states})
        self.assertEqual(revision.attestation.load(self.b,self.source),old)


if __name__=='__main__':unittest.main()
