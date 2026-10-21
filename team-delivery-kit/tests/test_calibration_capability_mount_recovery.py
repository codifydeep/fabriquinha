import contextlib
import copy
import json
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from broker import calibration_capability_mount_recovery as recovery
from broker import calibration_capability_review as capability


class MountRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.cfg=dict(source=dict(issue_id='source',author_task='author'),
            capability_request=dict(task_id='22222222-2222-4222-8222-222222222222'),image='sha256:'+'a'*64)
        self.s=dict(stage='blocked',category='capability_evidence_rejected',started=1,
            **{k:False for k in capability.FALSE_FLAGS})
        self.b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner',db=self.db,
            LOCK=threading.RLock(),docker=self.docker)
        self.key,self.identity=recovery.identity(self.b,self.cfg)
        self.old=dict(stage='create_intent',deadline=10,approval=False)
        p=copy.deepcopy(self.identity['payload'])
        self.info=dict(Id='container',Image=p['Image'],Config=p,Mounts=[],
            HostConfig={**p['HostConfig'],'Mounts':None},RestartCount=0,
            State=dict(Status='created',Running=False,Pid=0,StartedAt='0001-01-01T00:00:00Z',FinishedAt='0001-01-01T00:00:00Z'))
        capability.initialize(self.con);recovery.initialize(self.con)
        self.con.execute('CREATE TABLE validation_jobs(job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        self.con.execute('CREATE TABLE leases(status TEXT)')
        self.con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',(self.key,json.dumps(self.identity),json.dumps(self.old)))
        self.con.execute('INSERT INTO calibration_capability_reviews VALUES(?,?,?,?)',
            ('source','author',json.dumps(self.cfg),json.dumps(self.s)));self.con.commit()
        self.barrier=dict(stage='sealed',drained=True,operation_id='maintenance',namespace=self.b.PREFIX)
        self.calls=[]
        self.native=Mock()
        self.addCleanup(patch.stopall)
        patch.object(recovery.maintenance,'current',side_effect=lambda con:self.barrier).start()
        patch.object(recovery.capability,'Effects',return_value=SimpleNamespace(verify=self.native)).start()

    @contextlib.contextmanager
    def db(self):
        with self.con:yield self.con

    def docker(self,method,path,payload=None):
        self.calls.append((method,path))
        if method!='GET':raise AssertionError('recovery may not mutate Docker')
        if path.startswith('/images/'):return dict(Id=self.cfg['image'],Config=dict(Env=[]))
        return self.info

    def call(self,now=100):return recovery.recover(self.b,'source','author','maintenance',now=now)

    def state(self):return json.loads(self.con.execute('SELECT state FROM calibration_capability_reviews').fetchone()[0])

    def test_same_never_started_job_is_bound_atomically_without_create_or_start(self):
        receipt=self.call()
        self.assertEqual(self.state()['stage'],'measure')
        self.assertEqual(self.state()['started'],1)
        self.assertEqual(receipt['previous_job_state'],self.old)
        self.assertEqual(receipt['new_deadline'],700)
        self.assertEqual(receipt['previous_state'],self.s)
        self.assertTrue(all(m=='GET' for m,p in self.calls))
        self.assertEqual(recovery.qualified(self.con,self.cfg,self.state()),receipt)
        self.native.assert_called_once_with(self.cfg)
        for k in ('create_replayed','start_replayed','author_retry_authorized','source_reset','retry_budget_reset','delivery_approval'):
            self.assertIs(receipt[k],False)

    def test_repeated_invocation_does_not_renew_observation_window(self):
        receipt=self.call();calls=list(self.calls)
        self.assertEqual(self.call(now=1000),receipt)
        self.assertEqual(self.calls,calls)
        self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_capability_mount_recoveries').fetchone()[0],1)

    def test_started_or_mounted_or_policy_changed_container_is_rejected(self):
        original=copy.deepcopy(self.info)
        for mutate in (lambda i:i['State'].update(Status='running',Running=True,Pid=10),
                lambda i:i['State'].update(StartedAt='2026-01-01T00:00:00Z'),
                lambda i:i.update(RestartCount=1),
                lambda i:i.update(Mounts=[dict(Type='volume',Destination='/secret')]),
                lambda i:i['HostConfig'].update(Binds=['/private:/secret:ro']),
                lambda i:i['HostConfig'].update(NetworkMode='bridge'),
                lambda i:i['Config']['Labels'].update({'delivery-kit.owner':'foreign'})):
            self.info=copy.deepcopy(original);mutate(self.info)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.call()
            self.assertEqual(self.state(),self.s)

    def test_active_lease_or_unsealed_maintenance_forbids_recovery(self):
        self.barrier['stage']='draining'
        with self.assertRaises(ValueError):self.call()
        self.barrier['stage']='sealed';self.con.execute("INSERT INTO leases VALUES('running')");self.con.commit()
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.calls,[])

    def test_foreign_job_identity_or_already_measured_state_forbids_recovery(self):
        changed={**self.identity,'name':'foreign'}
        self.con.execute('UPDATE validation_jobs SET identity=?',(json.dumps(changed),));self.con.commit()
        with self.assertRaises(ValueError):self.call()
        self.con.execute('UPDATE validation_jobs SET identity=?',(json.dumps(self.identity),))
        self.con.execute('UPDATE calibration_capability_reviews SET state=?',(json.dumps({**self.s,'measurement':{}}),));self.con.commit()
        with self.assertRaises(ValueError):self.call()

    def test_fault_after_updates_rolls_back_receipt_and_both_states(self):
        with patch.object(recovery,'qualified',side_effect=ValueError('injected fault')):
            with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.state(),self.s)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM validation_jobs').fetchone()[0]),self.old)
        self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_capability_mount_recoveries').fetchone()[0],0)

    def test_changed_bound_container_or_deadline_invalidates_recovery(self):
        self.call();state=self.state()
        raw=self.con.execute('SELECT state FROM validation_jobs').fetchone()[0]
        for change in (dict(container_id='foreign'),dict(deadline=701)):
            self.con.execute('UPDATE validation_jobs SET state=?',(json.dumps({**json.loads(raw),**change}),))
            with self.assertRaises(ValueError):recovery.qualified(self.con,self.cfg,state)


if __name__=='__main__':unittest.main()
