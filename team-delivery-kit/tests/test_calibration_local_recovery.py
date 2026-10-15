import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from broker import generic_calibration_local_recovery as recovery,handoffs,generic_calibration_workflow as workflow
from generic_harness_calibration import digest
import test_calibration_capability_recovery as samples


class LocalRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=samples.CapabilityRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.con=f.con;f.migrate()
        self.c,self.s=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        self.s.update(stage='blocked',category='bundle_task_failed',observed_task='new-cto',wakeup_id='new-wake')
        self.t={**f.f.t,'id':'new-cto','wakeup_id':'new-wake'}
        self.b={**f.f.b,'task_id':'new-cto','scope':'workspace:cto:planning:new-cto'}
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(self.s),))
        handoffs.save(self.con,self.c['author_task'],self.c['issue_id'],'test_first_blocked',self.c['cto'],
            dict(calibration_prerequisite=self.s,error='generic_calibration_prerequisite:bundle_task_failed'),0)
        self.rejection=dict(operation='local_request_rejection_v1',execution_id=self.b['request_id'],
            request_sha256='a'*64,stage='read_dispatch',origin=dict(module='deterministic_read_dispatch',line=55),
            exception_type='ValueError',error_sha256=hashlib.sha256(b'invalid deterministic read contract').hexdigest(),
            retry_authorized=False,delivery_approval=False)
        self.proof=dict(operation='calibration_read_qualification_v1',passed=True,
            source_sha256=digest(self.c),sources={n:'b'*64 for n in recovery.SOURCES},
            proxy_image='sha256:'+'c'*64,delivery_approval=False)

    def run_recovery(self,**changes):
        c,s=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        args=dict(con=self.con,c=c,state=s,task=self.t,binding=self.b,tool_count=0,
            rejection=self.rejection,proof=self.proof,barrier=self.f.f.barrier,namespace='delivery-kit-port2',now=2)
        args.update(changes);return recovery.transition(**args)

    def test_exact_local_failure_can_resume_once_without_resetting_prior_ledger(self):
        before=self.con.execute('SELECT receipt FROM generic_calibration_capability_recoveries').fetchone()[0]
        receipt=self.run_recovery()
        c,s=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        self.assertEqual(c,self.c);self.assertEqual(s['stage'],'bundle_dispatch')
        self.assertEqual(receipt['prior_state'],self.s);self.assertEqual(receipt['attempt_limit'],1)
        self.assertFalse(receipt['author_restarted']);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(before,self.con.execute('SELECT receipt FROM generic_calibration_capability_recoveries').fetchone()[0])
        self.assertEqual(self.run_recovery(),receipt)
        s.update(stage='blocked',observed_task='later-failure')
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(s),));self.con.commit()
        self.assertEqual(self.run_recovery(),receipt)
        self.assertEqual(s,json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]))

    def test_unqualified_active_foreign_or_paid_failure_stays_blocked(self):
        for changes in (dict(tool_count=1),dict(task={**self.t,'status':'running'}),
                dict(task={**self.t,'agent_id':'foreign'}),dict(binding={**self.b,'status':'running'}),
                dict(barrier={**self.f.f.barrier,'stage':'released'}),
                dict(rejection={**self.rejection,'stage':'upstream'}),
                dict(rejection={**self.rejection,'error_sha256':'0'*64}),
                dict(rejection={**self.rejection,'execution_id':'foreign'}),
                dict(proof={**self.proof,'source_sha256':'0'*64}),
                dict(proof={**self.proof,'passed':False})):
            with self.assertRaises(ValueError):self.run_recovery(**changes)
        self.assertEqual(self.s,json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]))

    def test_atomic_parent_failure_preserves_original_hold(self):
        with patch.object(handoffs,'save',side_effect=ValueError('storage failed')):
            with self.assertRaises(ValueError):self.run_recovery()
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_local_recoveries').fetchone()[0],0)
        self.assertEqual(self.s,json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]))

    def test_lost_wakeup_ack_observes_same_new_marker_and_never_rewinds(self):
        self.run_recovery();events=[]
        class Effects:
            def verify(_,c):pass
            def reserve(_,c):return True
            def wake(_,c,note,marker,first):events.append((marker,first));raise TimeoutError()
        workflow.advance(self.con,self.c,Effects(),now=3);workflow.advance(self.con,self.c,Effects(),now=4)
        self.assertEqual(events[0][0],events[1][0]);self.assertEqual([e[1] for e in events],[True,False])
        s=json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
        s['local_recovery_sha256']='0'*64
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(s),));self.con.commit()
        workflow.advance(self.con,self.c,Effects(),now=5)
        self.assertEqual(len(events),2)
