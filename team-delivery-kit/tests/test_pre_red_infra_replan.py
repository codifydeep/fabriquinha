import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from broker import handoffs,pre_red_infra_replan as recovery,test_first_handoffs
from test_test_first_handoffs import Broker,Effects


class InfrastructureReplanTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.b=Broker(Path(temp.name)/'state.sqlite');self.b.STATE=Path(temp.name);self.b.LOCK=threading.RLock()
        self.b.IMAGE='sha256:'+'a'*64;(self.b.STATE/'native.json').write_text('{}')
        self.issue='11111111-1111-4111-8111-111111111111'
        self.source='22222222-2222-4222-8222-222222222222'
        self.cto='33333333-3333-4333-8333-333333333333'
        self.payload=dict(issue_id=self.issue,source_task=self.source,cto_task=self.cto)
        self.route=dict(issue_id=self.issue,author='author',cto='cto',enabled=True,test_first=True,
                        test_first_files=['tests/test_new.py'],minimum_calls=8)
        self.decision=dict(action='escalate_cto',reason='Need infrastructure evidence.',optional_files=[])
        self.data=dict(phase='test_first',error='test_first_cto_requires_replanning',
            blocked_cause='test_author_execution_failed',cto_task=self.cto,decision=self.decision,
            test_first_cto_wakeup='cto-wake')
        self.runs=[dict(id=self.source,agent_id='author',status='failed',created_at='02'),
                   dict(id=self.cto,agent_id='cto',status='completed',wakeup_id='cto-wake')]
        self.proof=dict(verified=True,baseline_unchanged=True,manifest_sha256='b'*64,volume='frozen')
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT)')
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            c.execute('CREATE TABLE tool_events(request_id TEXT,tool_count INTEGER)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',(self.issue,json.dumps(self.route)))
            c.execute('INSERT INTO native_bindings VALUES (?,?)',('execution',self.source))
            c.execute('INSERT INTO leases VALUES (?,?)',('execution','expired'))
            handoffs.save(c,self.source,self.issue,'test_first_blocked','cto',self.data,1)

    def register(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs),patch(
                'broker.handoff_runtime.Effects.decision',return_value=self.decision),patch(
                'broker.artifact_transport_recovery.verify_preserved_failure',return_value=self.proof):
            return recovery.register(self.b,self.payload)

    def test_verified_registration_is_once_preserves_blocker_and_creates_no_red(self):
        receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertEqual(receipt['previous_blocker'],self.data)
        self.assertFalse(receipt['author_retry_authorized'])
        with self.b.db() as c:
            row=handoffs.load(c,self.source)
            self.assertEqual(row['stage'],'technical_decision_required')
            self.assertTrue(recovery.qualified(c,self.issue,self.source,json.loads(row['data'])))
            self.assertIsNone(c.execute('SELECT 1 FROM test_first_red').fetchone())
            self.assertEqual(c.execute('SELECT count(*) FROM pre_red_infra_replans').fetchone()[0],1)

    def test_closed_prompt_bound_failure_requires_mechanical_context_repair(self):
        from generated_context import START, END
        self.runs[0]['error']='restricted broker stream failed: native_prompt_bounds'
        with self.b.db() as c:
            c.execute("UPDATE leases SET status='closed'")
        description=('Acceptance\nApproved CEO request: '+'x'*3300+
                     '\nBinding CTO proposal: unchanged\n'+START+'["tests/test_new.py"]'+END)
        with patch('broker.native.issue_record',return_value={'description':description}):
            receipt=self.register()
        self.assertEqual(receipt['prompt_presentation']['operation'],'generated_policy_presentation_v1')
        self.assertLessEqual(receipt['prompt_presentation']['effective_characters'],4000)
        self.assertFalse(receipt['author_retry_authorized'])

    def test_closed_failure_without_context_proof_remains_blocked(self):
        self.runs[0]['error']='restricted broker stream failed: native_prompt_bounds'
        with self.b.db() as c:c.execute("UPDATE leases SET status='closed'")
        with patch('broker.native.issue_record',return_value={'description':'x'*4222}):
            with self.assertRaises(ValueError):self.register()

    def test_forged_receipt_or_other_source_cannot_bypass_diagnosis(self):
        self.register()
        with self.b.db() as c:
            data=json.loads(handoffs.load(c,self.source)['data'])
            self.assertFalse(recovery.qualified(c,self.issue,'other',data))
            data['infrastructure_replan']['proof']['baseline_unchanged']=False
            self.assertFalse(recovery.qualified(c,self.issue,self.source,data))

    def test_live_worker_red_or_nonzero_tools_fail_closed(self):
        for sql,args in [('INSERT INTO leases VALUES (?,?)',('other','running')),
                         ('INSERT INTO test_first_red VALUES (?)',(self.issue,)),
                         ('INSERT INTO tool_events VALUES (?,?)',('execution',1))]:
            with self.b.db() as c:c.execute(sql,args)
            with self.assertRaises(ValueError):self.register()
            with self.b.db() as c:
                c.execute("DELETE FROM leases WHERE request_id='other'")
                c.execute('DELETE FROM test_first_red');c.execute('DELETE FROM tool_events')
                self.assertEqual(handoffs.load(c,self.source)['stage'],'test_first_blocked')

    def test_wrong_cto_wakeup_or_later_author_cannot_replan(self):
        self.runs[1]['wakeup_id']='wrong'
        with self.assertRaises(ValueError):self.register()
        self.runs[1]['wakeup_id']='cto-wake'
        self.runs.append(dict(id='later',agent_id='author',status='failed',created_at='03'))
        with self.assertRaises(ValueError):self.register()

    def test_changed_baseline_is_not_infrastructure_recovery(self):
        self.proof['baseline_unchanged']=False
        with self.assertRaises(ValueError):self.register()

    def test_changed_registered_identity_is_rejected(self):
        self.register();self.payload['cto_task']='44444444-4444-4444-8444-444444444444'
        with self.assertRaises(ValueError):self.register()

    def test_existing_pipeline_requests_new_cto_not_author(self):
        self.register()
        with self.b.db() as c:
            # A historical CTO diagnosis must not suppress this qualified replan.
            handoffs.save(c,'old',self.issue,'test_first_blocked','cto',{'test_first_cto_wakeup':'older'},0)
            row=handoffs.load(c,self.source)
        effects=Effects(self.b)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],row,effects)
        self.assertEqual(len(effects.wakeups),1)
        self.assertEqual(effects.wakeups[0][0][1],'cto')
        self.assertIn('DELIVERY_TYPED_DECISION_V1',effects.wakeups[0][0][4])
        with self.b.db() as c:row=handoffs.load(c,self.source)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],row,effects)
        self.assertEqual(len(effects.wakeups),1)


if __name__=='__main__':unittest.main()
