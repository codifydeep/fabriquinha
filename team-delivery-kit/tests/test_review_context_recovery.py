import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from broker import review_context_recovery as recovery, handoffs
from test_test_first_handoffs import Broker


class ReviewContextRecoveryTests(unittest.TestCase):
    def test_real_prompt_probe_uses_task_id_without_mutating_live_handoff(self):
        instruction='Read the immutable delivery and the complete controller TDD receipt.'
        marker='c'*64
        recorded={**self.recorded,'author':'author','reviewer':'reviewer',
                  'dispatch_marker':marker,'instruction':instruction}
        failed={**self.runs[1],'handoff_note':'DELIVERY_HANDOFF '+marker+'\n'+instruction+'\n'+'x'*4100}
        with patch.dict('os.environ',{'BROKER_WORKER_IMAGE':'sha256:'+'d'*64}):
            proof=recovery.probe(self.b,dict(id=self.issue,title='Frontend',description='Complete acceptance.'),
                                  failed,recorded)
        self.assertFalse(proof['approval']);self.assertEqual(proof['source_task'],self.source)
        self.assertLess(proof['effective_characters'],4000);self.assertLess(proof['prompt_characters'],10000)
        with self.b.db() as c:
            self.assertEqual(handoffs.load(c,self.source)['stage'],'technical_decision_required')
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='review_context_presentations'").fetchone())
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.b=Broker(Path(tmp.name)/'leases.sqlite');self.b.STATE=Path(tmp.name)
        self.b.LOCK=threading.RLock();self.b.__file__=str(Path(__file__).parents[1]/'broker/server.py')
        (self.b.STATE/'native.json').write_text('{}')
        self.issue='11111111-1111-4111-8111-111111111111'
        self.source='22222222-2222-4222-8222-222222222222'
        self.failed='33333333-3333-4333-8333-333333333333'
        self.payload=dict(issue_id=self.issue,source_task=self.source,failed_review=self.failed)
        self.route=dict(enabled=True,author='author',reviewer='reviewer',techlead='lead',cto='cto')
        self.evidence=dict(manifest_sha256='a'*64,tests=301,baseline_tests_intact=True,
                           tdd=dict(green=dict(executed_by_controller=True)))
        self.snapshot=dict(task_id=self.source,status='complete',volume='frozen')
        self.data=dict(source_task=self.source,review_retries=1,error='recipient_execution_failed',
            failed_dispatch_stage='ready_review',recipient_error=recovery.ERROR,
            required_action='diagnose_repeated_review_execution_failure',
            decision=dict(action='retry_review',optional_files=[]),snapshot=self.snapshot,
            evidence=self.evidence,recipient_task='diagnosis',wakeup_id='diagnosis-wake')
        self.recorded=dict(source_task=self.source,wakeup_id='failed-wake',dispatch_stage='ready_review',
                           target='reviewer',snapshot=self.snapshot,evidence=self.evidence)
        self.runs=[dict(id=self.source,status='completed',agent_id='author',created_at='01'),
            dict(id=self.failed,status='failed',agent_id='reviewer',wakeup_id='failed-wake',error=recovery.ERROR),
            dict(id='diagnosis',status='completed',agent_id='lead',wakeup_id='diagnosis-wake')]
        self.presentation=dict(approval=False,source_task=self.source,manifest_sha256='a'*64,
                               original_characters=4193,effective_characters=3427,prompt_characters=7894)
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT)')
            c.execute('CREATE TABLE tool_events(request_id TEXT,tool_count INT)')
            c.execute('CREATE TABLE snapshots(task_id TEXT,status TEXT)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',(self.issue,json.dumps(self.route)))
            c.execute('INSERT INTO snapshots VALUES (?,?)',(self.source,'complete'))
            c.execute('INSERT INTO leases VALUES (?,?)',('request','closed'))
            c.execute('INSERT INTO native_bindings VALUES (?,?)',('request',self.failed))
            handoffs.save(c,self.source,self.issue,'awaiting_acceptance','reviewer',self.recorded,1)
            handoffs.save(c,self.source,self.issue,'technical_decision_required','cto',self.data,2)

    def register(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs),patch(
            'broker.native.issue_record',return_value=dict(id=self.issue)),patch.object(
            recovery,'probe',return_value=self.presentation),patch(
            'broker.handoff_runtime.Effects.validate',return_value=self.evidence):
            return recovery.register(self.b,self.payload)

    def test_once_preserves_counter_delivery_and_requires_fresh_cto_decision(self):
        receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertFalse(receipt['approval']);self.assertFalse(receipt['author_restarted'])
        self.assertEqual(receipt['previous_blocker'],self.data)
        with self.b.db() as c:
            row=handoffs.load(c,self.source);data=json.loads(row['data'])
            self.assertEqual(row['stage'],'diagnose_cto');self.assertEqual(data['review_retries'],1)
            self.assertEqual(data['snapshot'],self.snapshot);self.assertEqual(data['evidence'],self.evidence)
            self.assertNotIn('decision',data);self.assertNotIn('review_context_recovery_used',data)
            self.assertTrue(recovery.qualified(c,self.issue,self.source,data))
            self.assertFalse(recovery.qualified(c,self.issue,self.source,{**data,'review_context_recovery':{}}))
        self.payload['failed_review']=self.source
        with self.assertRaises(ValueError):self.register()

    def test_wrong_actor_failure_or_live_task_cannot_qualify(self):
        original=copy.deepcopy(self.runs)
        for key,value in [('status','completed'),('agent_id','author'),('error','functional failure'),('wakeup_id','stale')]:
            self.runs[1][key]=value
            with self.assertRaises(ValueError):self.register()
            self.runs=copy.deepcopy(original)
        self.runs[2]['status']='running'
        with self.assertRaises(ValueError):self.register()

    def test_tool_execution_snapshot_drift_and_source_pin_fail_closed(self):
        with self.b.db() as c:c.execute('INSERT INTO tool_events VALUES (?,?)',('request',1))
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as c:c.execute('DELETE FROM tool_events')
        self.presentation['manifest_sha256']='b'*64
        with self.assertRaises(ValueError):self.register()
        self.presentation['manifest_sha256']='a'*64
        with patch.object(recovery,'FIXED_SERVER_SHA','0'*64):
            with self.assertRaises(ValueError):self.register()
