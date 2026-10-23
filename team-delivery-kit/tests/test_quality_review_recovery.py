"""Scoped pre-admission recovery on durable fixtures, not native qualification."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from broker import quality_review_recovery as recovery,quality_test_review as review,quality_review_launch as launch
import test_quality_team_progress as fixtures


class ReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.TeamProgressTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b=self.f.b;self.source=self.f.source;self.r=self.f.f
        with patch.object(review.native,'ensure_review_start',return_value=self.r.wakeup):self.f.call()
        self.context,self.before=review.load(self.b,self.source)
        self.failed={**self.r.native_task(),'status':'failed','scope_note_envelope_verified':True,
            'scope_note_envelope_sha256':'d'*64}
        self.operation='80000000-0000-4000-8000-000000000001'
        self.sha=hashlib.sha256(Path(recovery.native.__file__).read_bytes()).hexdigest()
        with self.b.db() as con:
            review.maintenance.initialize(con)
            receipt=dict(stage='sealed',namespace=self.b.PREFIX,operation_id=self.operation,drained=True)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(self.operation,'sealed',json.dumps(receipt)))
        self.records={self.failed['id']:self.failed,self.source:self.r.capture.native}
        self.runs=[self.r.capture.native,self.failed]
        for target,name,value in [(recovery.native,'task_record',lambda settings,task,actor:self.records[task]),
                (recovery.native,'issue_task_runs',lambda *a:list(self.runs)),
                (recovery.native,'task_messages',lambda *a:[]),(recovery.maintenance,'native_active',lambda *a:[])]:
            p=patch.object(target,name,side_effect=value);p.start();self.addCleanup(p.stop)

    def register(self):return recovery.register(self.b,self.source,self.failed['id'],self.sha,self.operation)

    def count(self):
        with self.b.db() as con:return con.execute('SELECT count(*) FROM grants').fetchone()[0]

    def test_atomic_registration_preserves_context_red_old_task_and_is_idempotent(self):
        receipt=self.register();self.assertEqual(self.register(),receipt)
        context,state=review.load(self.b,self.source)
        self.assertEqual(context,self.context);self.assertEqual(state['stage'],'prepared')
        self.assertNotEqual(state['recovery_marker'],context['marker']);self.assertEqual(self.count(),1)
        self.assertEqual(receipt['previous_review_state'],self.before)
        self.assertEqual(receipt['previous_team_state']['stage'],'awaiting_review_admission')
        self.assertFalse(receipt['tests_approved']);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(self.failed['status'],'failed')
        self.assertEqual(recovery.activation_ready(self.b,self.r.e.issue,self.operation),receipt)
        with self.assertRaises(ValueError):recovery.activation_ready(self.b,self.r.e.issue,'80000000-0000-4000-8000-000000000009')

    def test_wrong_adapter_running_task_or_preexisting_admission_never_retries(self):
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,self.failed['id'],'0'*64,self.operation)
        self.failed['status']='running'
        with self.assertRaises(ValueError):self.register()
        self.failed['status']='failed'
        with self.b.db() as con:
            con.execute('INSERT INTO quality_review_admissions VALUES(?,?,?,?,?)',(self.source,self.failed['id'],'occupied','{}','invalid'))
        with self.assertRaises(ValueError):self.register()
        self.assertIsNone(recovery.load(self.b,self.source));self.assertEqual(review.load(self.b,self.source)[1],self.before)

    def dispatch(self):
        self.register();review.maintenance.release(self.b,self.operation)
        self.new_wakeup={**self.r.wakeup,'id':'80000000-0000-4000-8000-000000000002'}
        with patch.object(review.native,'ensure_review_start',return_value=self.new_wakeup) as wake:
            state=review.dispatch(self.b,self.source)
        self.assertEqual(wake.call_args.args[4],state['recovery_marker'])
        self.new_task={**self.r.native_task(),'id':'80000000-0000-4000-8000-000000000003',
            'wakeup_id':self.new_wakeup['id'],'handoff_note':review.note(self.b,self.context,state)}
        self.records[self.new_task['id']]=self.new_task;self.runs.append(self.new_task)
        return state

    def test_only_new_exact_review_can_be_admitted_and_current_binding_remains_valid(self):
        state=self.dispatch()
        grant=review.admit(self.b,self.source,self.new_task['id'],self.r.e.reviewer)
        with self.b.db() as con:self.assertEqual(review.admission(con,grant['request_id'])['phase'],'test_review_v2')
        self.assertEqual(self.count(),2)
        current=launch.current(self.b,grant['request_id'])
        self.assertEqual(current['task_id'],self.new_task['id'])
        self.assertEqual(current['handoff_note'],self.new_task['handoff_note'])
        with self.assertRaises(ValueError):review.admit(self.b,self.source,self.failed['id'],self.r.e.reviewer)
        self.assertEqual(recovery.load(self.b,self.source)['previous_review_state']['wakeup_id'],self.before['wakeup_id'])

    def test_unknown_extra_run_is_not_silently_ignored(self):
        self.dispatch();self.runs.append({**self.new_task,'id':'80000000-0000-4000-8000-000000000004','status':'failed'})
        with self.assertRaises(ValueError):review.admit(self.b,self.source,self.new_task['id'],self.r.e.reviewer)
        self.assertEqual(self.count(),1)

    def test_a_second_recovery_or_late_change_to_the_old_failed_task_is_rejected(self):
        self.register()
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,'80000000-0000-4000-8000-000000000005',self.sha,self.operation)
        context,state=review.load(self.b,self.source)
        self.failed['status']='completed'
        with self.assertRaises(ValueError):review.eligible_runs(self.b,context,state,[self.failed])


if __name__=='__main__':unittest.main()
