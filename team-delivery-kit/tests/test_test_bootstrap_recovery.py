import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from broker import handoffs,test_bootstrap_recovery
from test_test_first_handoffs import Broker,Effects
from broker import test_first_handoffs


class BootstrapRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.b=Broker(Path(temp.name)/'state.sqlite');self.b.STATE=Path(temp.name)
        self.b.LOCK=threading.RLock();self.b.PREFIX='isolated';self.b.IMAGE='sha256:'+'a'*64
        (self.b.STATE/'native.json').write_text('{}')
        self.issue='11111111-1111-4111-8111-111111111111'
        self.source='22222222-2222-4222-8222-222222222222'
        self.payload={'issue_id':self.issue,'source_task':self.source,'worker_image':self.b.IMAGE}
        self.route={'issue_id':self.issue,'test_first':True,'enabled':True,'author':'author',
                    'cto':'cto','test_first_files':['tests/test_new.py'],'minimum_calls':8}
        self.data={'phase':'test_first','diagnostic':None,'error':'test_first_cto_invalid_decision:JSONDecodeError'}
        self.calls=[]
        self.b.seed_workspace=lambda *args:self.calls.append('seed')
        self.b.lock_workspace=lambda *args:self.calls.append('fence')
        self.runs=[{'id':self.source,'agent_id':'author','status':'failed',
                    'error':'hermes initialize failed: hermes process exited','created_at':'01'}]
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            c.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT,state TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,scope TEXT,agent_id TEXT,task_id TEXT)')
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            c.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',(self.issue,json.dumps(self.route)))
            c.execute('INSERT INTO test_revision_trials VALUES (?,?,?)',(self.issue,json.dumps(
                {'parent_issue':'parent','cto_decision':'decision','reason':'preserve assertions'}),'{}'))
            c.execute('INSERT INTO test_revision_trials VALUES (?,?,?)',('parent','{}',json.dumps(
                {'size_invalidation':{'facts':True},
                 'rejection_diagnosis':{'decision_task':'decision','decision':{'action':'request_test_revision'}}})))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('request','scope','author',self.source))
            c.execute('INSERT INTO leases VALUES (?,?)',('request','failed'))
            c.execute('INSERT INTO broker_errors VALUES (?,?,?)',('request','transport_start','bootstrap:broker_internal'))
            handoffs.save(c,self.source,self.issue,'test_first_blocked','cto',self.data,1)

    def resume(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs),patch(
                'broker.test_revision_review.seed_source',return_value={'selection':{'repair_input_bytes':{'tests/test_new.py':38510}}}):
            return test_bootstrap_recovery.reopen(self.b,self.payload)

    def test_probes_once_preserves_bad_decision_and_dispatches_one_author(self):
        first=self.resume();self.assertEqual(first,self.resume())
        self.assertEqual(self.calls,['seed','fence'])
        self.assertEqual(first['previous_blocker'],self.data)
        with self.b.db() as c:prior=handoffs.load(c,self.source)
        effects=Effects(self.b)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],prior,effects)
        self.assertEqual(len(effects.wakeups),1)
        self.assertEqual(effects.wakeups[0][0][1],'author')
        with self.b.db() as c:
            state=handoffs.load(c,self.source)
            self.assertIsNone(c.execute('SELECT 1 FROM test_first_red').fetchone())
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],state,effects)
        self.assertEqual(len(effects.wakeups),1)

    def test_rejects_live_workers_or_existing_red(self):
        with self.b.db() as c:c.execute('INSERT INTO leases VALUES (?,?)',('other','running'))
        with self.assertRaisesRegex(ValueError,'idle'):self.resume()
        with self.b.db() as c:
            c.execute("DELETE FROM leases WHERE request_id='other'")
            c.execute('INSERT INTO test_first_red VALUES (?)',(self.issue,))
        with self.assertRaisesRegex(ValueError,'Red already'):self.resume()
        self.assertEqual(self.calls,[])

    def test_failed_probe_cannot_reopen_or_grant_work(self):
        self.b.lock_workspace=lambda *args:(_ for _ in ()).throw(ValueError('still broken'))
        with self.assertRaisesRegex(ValueError,'still broken'):self.resume()
        with self.b.db() as c:self.assertEqual(handoffs.load(c,self.source)['stage'],'test_first_blocked')

    def test_rejects_wrong_image_and_later_author(self):
        self.payload['worker_image']='sha256:'+'b'*64
        with self.assertRaisesRegex(ValueError,'image'):self.resume()
        self.payload['worker_image']=self.b.IMAGE
        self.runs.append({'id':'later','agent_id':'author','status':'failed','created_at':'02'})
        with self.assertRaisesRegex(ValueError,'latest'):self.resume()

    def test_formatted_recovery_uses_exact_completed_same_workspace_author_once(self):
        completed='44444444-4444-4444-8444-444444444444'
        self.runs.insert(0,{'id':completed,'agent_id':'author','status':'completed','created_at':'00'})
        self.data['error']='test_first_correction_failed_after_cto_diagnosis'
        with self.b.db() as c:
            handoffs.save(c,self.source,self.issue,'test_first_blocked','cto',self.data,1)
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('old','scope','author',completed))
        payload={**self.payload,'completed_source':completed,'test_sha256':'b'*64}
        with patch('broker.native.issue_task_runs',return_value=self.runs),patch(
                'broker.test_revision_review.seed_source',return_value={'selection':{'repair_input_bytes':{'tests/test_new.py':38510}}}),patch(
                'broker.test_normalization_job.run',return_value={'identical_ast':True,'formatted_bytes':123}) as job:
            result=test_bootstrap_recovery.reopen(self.b,payload,normalized=True)
            self.assertEqual(test_bootstrap_recovery.reopen(self.b,payload,normalized=True),result)
        job.assert_called_once()
        self.assertEqual(self.calls,['fence'])
        self.assertEqual(result['normalization']['formatted_bytes'],123)
