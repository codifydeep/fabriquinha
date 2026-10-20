import json
import sqlite3
import unittest

from broker import calibration_admission_recovery as recovery
from generic_harness_calibration import digest


class AdmissionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.row_factory=sqlite3.Row
        self.con.execute('CREATE TABLE calibration_read_recoveries(recovery_id TEXT PRIMARY KEY,config TEXT,state TEXT)')
        self.cfg=dict(source=dict(cto='cto',author_task='author',issue_id='product'))
        self.state=dict(stage='blocked',category='dependency_evidence_rejected',issue_id='spike',
            owner='cto',wakeup_id='wake',marker='a'*64,measurement={'immutable':'bytes'},
            delivery_approval=False,execution_authorized=False,source_reset=False,author_retry_authorized=False)
        self.task=dict(id='task',agent_id='cto',issue_id='spike',wakeup_id='wake',status='failed',
            started_at='2026-10-20T21:25:27Z',completed_at='2026-10-20T21:25:42Z',
            error='hermes initialize failed: hermes process exited',failure_reason='agent_error.process_failure')
        self.binding=dict(task_id='task',agent_id='cto',issue_id='spike',request_id='request',scope='workspace:cto:planning:task')
        self.grant=dict(task_id='task',attempt=1,mode='planning',request_id='request',deadline=1792532027.5787756,used=0)
        self.counts={t:0 for t in recovery.EMPTY_TABLES}
        self.installation=dict(operation='installed_admission_isolation_v1',runtime_image=recovery.RUNTIME_IMAGE,
            source_hashes=dict(recovery.SOURCE_HASHES),lock_isolation=True,shared_lane_lock=True)
        self.barrier=dict(operation_id='maintenance',namespace='owned',stage='sealed',drained=True)
        self.con.execute('INSERT INTO calibration_read_recoveries VALUES(?,?,?)',
            ('recovery',json.dumps(self.cfg),json.dumps(self.state)))

    def qualify(self,**changes):
        args=dict(task=self.task,binding=self.binding,grant=self.grant,counts=self.counts,
            installation=self.installation,barrier=self.barrier,namespace='owned',now=1792534000)
        args.update(changes)
        return recovery.transition(self.con,'recovery',self.cfg,self.state,**args)

    def test_only_pre_prompt_assessment_is_rearmed_with_old_evidence_preserved(self):
        receipt=self.qualify()
        state=json.loads(self.con.execute('SELECT state FROM calibration_read_recoveries').fetchone()[0])
        self.assertEqual(state['stage'],'cto_dispatch')
        self.assertEqual(state['measurement'],self.state['measurement'])
        self.assertEqual(receipt['previous_state'],self.state)
        self.assertGreater(receipt['admission_issued_at'],receipt['native_completed_at'])
        self.assertEqual(receipt['infrastructure_attempt_limit'],1)
        self.assertEqual(state['admission_recovery_sha256'],digest(receipt))
        for key in ('delivery_approval','execution_authorized','source_reset','author_retry_authorized','retry_budget_reset'):
            self.assertIs(receipt[key],False)
        self.assertEqual(recovery.qualified(self.con,'recovery',self.cfg,state),receipt)

    def test_used_grant_any_worker_effect_or_live_capability_forbids_recovery(self):
        cases=[dict(grant={**self.grant,'used':1}),dict(now=self.grant['deadline']-1)]
        cases += [dict(counts={**self.counts,table:1}) for table in self.counts]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.qualify(**changes)

    def test_earlier_admission_and_unrelated_failure_are_not_eligible(self):
        for changes in (dict(grant={**self.grant,'deadline':1792531540+480}),
                dict(task={**self.task,'failure_reason':'agent_error.provider_server_error'}),
                dict(binding={**self.binding,'agent_id':'author'}),
                dict(task={**self.task,'wakeup_id':'other'})):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.qualify(**changes)

    def test_maintenance_and_installed_sources_are_not_agent_assertions(self):
        for changes in (dict(barrier={**self.barrier,'stage':'released'}),
                dict(installation={**self.installation,'lock_isolation':False}),
                dict(installation={**self.installation,'source_hashes':{}})):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.qualify(**changes)

    def test_no_second_recovery_or_stale_parent_overwrite(self):
        self.qualify()
        with self.assertRaises(ValueError):self.qualify()
        self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_admission_recoveries').fetchone()[0],1)

    def test_recovery_and_state_update_roll_back_together(self):
        self.con.commit()
        self.con.execute("CREATE TRIGGER deny_change BEFORE UPDATE ON calibration_read_recoveries BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.qualify()
        self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_admission_recoveries').fetchone()[0],0)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM calibration_read_recoveries').fetchone()[0]),self.state)

    def test_mutated_measurement_cannot_use_previous_receipt(self):
        self.qualify()
        state=json.loads(self.con.execute('SELECT state FROM calibration_read_recoveries').fetchone()[0])
        state['measurement']={'changed':True}
        with self.assertRaises(ValueError):recovery.qualified(self.con,'recovery',self.cfg,state)
