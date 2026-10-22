"""First Green admission from an authenticated freeze; fixture native authority."""
import hashlib
import json
import unittest
from unittest.mock import patch
from broker import quality_implementation_admission as implementation
import test_quality_review_attestation as fixtures


class ImplementationAdmissionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityReviewAttestationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.source=f.source;self.frozen=f.call()
        self.assertEqual(self.frozen['stage'],'tests_frozen')
        self.b.QUALITY_IMPLEMENTATION_ENABLED=True
        self.task='90000000-0000-4000-8000-000000000001'
        self.wakeup=dict(id='90000000-0000-4000-8000-000000000002',issue_id=self.frozen['plan']['issue_id'],agent_id=self.frozen['plan']['author'])
        context,_=implementation.register(self.b,self.source)
        with patch.object(implementation.native,'ensure_scope_author_start',return_value=self.wakeup):
            implementation.dispatch(self.b,self.source)
        self.native=dict(id=self.task,agent_id=self.frozen['plan']['author'],issue_id=self.frozen['plan']['issue_id'],
            status='running',workspace_id=f.f.f.e.settings['workspace_id'],runtime_id=f.f.f.e.settings['runtime_id'],
            wakeup_id=self.wakeup['id'],created_at='2026-10-22T02:00:00Z',
            handoff_note='DELIVERY_SCOPE_AUTHOR_START '+context['marker']+'\nSource: '+self.frozen['review_task']+'\n'+context['instruction'])
        old_source=f.f.f.capture.native;old_review=f.f.record
        def lookup(settings,task,agent):
            return self.native if task==self.task else old_source if task==self.source else old_review
        for name,value in [('task_record',lookup),('issue_task_runs',lambda *_:[old_source,old_review,self.native])]:
            p=patch.object(implementation.native,name,side_effect=value);p.start();self.addCleanup(p.stop)

    def call(self):return implementation.admit(self.b,self.source,self.task,self.native['agent_id'])

    def test_single_frozen_implementation_grant_preserves_test_and_snapshot_identity(self):
        grant=self.call()
        with self.b.db() as con:
            context=implementation.load(con,grant['request_id'])
            token_hash=con.execute('SELECT digest FROM grants WHERE request_id=?',(grant['request_id'],)).fetchone()[0]
        self.assertEqual(token_hash,hashlib.sha256(grant['capability'].encode()).hexdigest())
        self.assertEqual(context['phase'],'implementation_v2')
        selected=implementation.selection(self.b,grant['request_id'])
        self.assertEqual(selected['editable_paths'],['/workspace/app.py'])
        self.assertEqual(selected['frozen_seed']['manifest_sha256'],self.frozen['manifest_sha256'])
        self.assertEqual(selected['frozen_tests'],self.frozen['frozen_tests'])
        self.assertEqual(selected['test_commands'],[])
        self.assertFalse(selected['delivery_approval'])
        with self.assertRaises(ValueError):self.call()

    def test_wrong_author_wakeup_or_nonrunning_native_task_cannot_get_product_permission(self):
        for key,value in [('wakeup_id',self.source),('status','completed'),('agent_id',self.b.QUALITY_CTO),('runtime_id','other')]:
            original=self.native[key];self.native[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):self.call()
            self.native[key]=original

    def test_missing_or_changed_freeze_never_falls_back_to_tests_only_or_legacy(self):
        with self.b.db() as con:con.execute('DELETE FROM quality_review_attestations')
        with self.assertRaises(ValueError):self.call()

    def test_operator_maintenance_or_capacity_does_not_mint_a_partial_phase(self):
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                ('operation','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_implementation_admissions').fetchone()[0],0)

    def test_snapshot_recreation_rejects_even_when_its_name_is_unchanged(self):
        self.f.f.volume_info['CreatedAt']='2026-10-22T03:00:00Z'
        with self.assertRaises(ValueError):self.call()

    def test_base_drift_cannot_apply_old_test_approval_to_a_new_git_base(self):
        self.b.issue_base.return_value={**self.b.issue_base.return_value,'base_sha':'c'*40}
        with self.assertRaises(ValueError):self.call()

    def test_dispatch_unknown_ack_never_reposts_original_wakeup(self):
        # New isolated run state, before any native wakeup/admission exists.
        with self.b.db() as con:
            row=con.execute('SELECT state FROM quality_implementation_handoffs').fetchone()
            state=json.loads(row[0]);state['stage']='prepared';state.pop('wakeup_id')
            state.pop('deadline')
            con.execute('UPDATE quality_implementation_handoffs SET state=?,state_sha256=?',
                (json.dumps(state),implementation.quality.digest(state)))
        with patch.object(implementation.native,'ensure_scope_author_start',side_effect=TimeoutError) as start:
            for _ in range(2):
                with self.assertRaises(implementation.validation_job.Pending):implementation.dispatch(self.b,self.source)
        self.assertTrue(start.call_args_list[0].kwargs['allow_create'])
        self.assertFalse(start.call_args_list[1].kwargs['allow_create'])
        self.assertEqual(start.call_args_list[0].args,start.call_args_list[1].args)

    def test_tool_configuration_has_no_test_editables_or_legacy_commands(self):
        grant=self.call()
        from quality_phase_tools import validate
        config=implementation.tool_config(self.b,grant['request_id']);validate(config,grant['request_id'])
        self.assertEqual(config['editable_paths'],['/workspace/app.py'])

    def reset_dispatch(self):
        with self.b.db() as con:
            row=con.execute('SELECT state FROM quality_implementation_handoffs').fetchone()
            state=json.loads(row[0]);state['stage']='prepared'
            for key in ('wakeup_id','deadline'):state.pop(key,None)
            con.execute('UPDATE quality_implementation_handoffs SET state=?,state_sha256=?',
                (json.dumps(state),implementation.quality.digest(state)))

    def test_capacity_wait_is_durable_bounded_and_does_not_wake_a_busy_author(self):
        self.reset_dispatch()
        with self.b.db() as con:
            for n in (1,2):con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('busy-'+str(n),'running'))
        with patch.object(implementation.native,'ensure_scope_author_start') as wake:
            for now in (1000,1700):
                with patch.object(implementation.time,'time',return_value=now),self.assertRaises(implementation.validation_job.Pending):
                    implementation.dispatch(self.b,self.source)
            _,state=implementation.handoff(self.b,self.source)
            self.assertEqual(state['capacity_since'],1000)
            self.assertTrue(state['capacity_alert'])
            with patch.object(implementation.time,'time',return_value=2801):
                state=implementation.dispatch(self.b,self.source)
            self.assertEqual(state['stage'],'technical_blocked')
            self.assertEqual(state['incident']['category'],'implementation_capacity_starvation')
            self.assertFalse(state['incident']['automatic_retry'])
            wake.assert_not_called()

    def test_full_capacity_never_partially_admits_and_freed_capacity_can_continue(self):
        with self.b.db() as con:
            for n in (1,2):con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('busy-'+str(n),'running'))
        with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_implementation_admissions').fetchone()[0],0)
            con.execute('DELETE FROM leases WHERE request_id LIKE ?',('busy-%',))
        self.assertEqual(self.call()['mode'],'implementation')


if __name__=='__main__':unittest.main()
