import copy,sqlite3,unittest
from contextlib import contextmanager
from types import SimpleNamespace
import threading,json
from broker import worker_creation_intent as intent


class WorkerCreationIntentTests(unittest.TestCase):
    def inputs(self):
        payload=dict(Image='sha256:'+'a'*64,User='10000:10000',Entrypoint=['python'],Cmd=['-c','sleep'],NetworkDisabled=False,
            Env=['DELIVERY_EXECUTION_MODE=implementation'],Labels={'delivery-kit.owner':'owner','delivery-kit.request':'request'},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='model',CapDrop=['ALL'],Mounts=[{'Source':'owned','Target':'/workspace'}]))
        info=dict(Id='b'*64,Image=payload['Image'],Config={k:copy.deepcopy(v) for k,v in payload.items() if k not in ('Image','HostConfig')},
            HostConfig=copy.deepcopy(payload['HostConfig']),State=dict(Status='created',StartedAt='never'))
        state=dict(stage='create_outcome_unknown',delivery_approval=False)
        return payload,state,info

    def test_late_ack_never_starts_a_terminal_task_or_grants_retry(self):
        payload,state,info=self.inputs()
        for native_status in ('failed','completed','cancelled'):
            new,lease=intent.observe(payload,state,info,native_status,1000,10)
            self.assertEqual(new['stage'],'late_container_observed');self.assertEqual(lease,'failed')
            self.assertFalse(new['author_retry_authorized']);self.assertFalse(new['delivery_approval'])
            self.assertEqual(new['fact']['container_id'],info['Id'])
            self.assertNotIn('Env',new['fact'])
        new,lease=intent.observe(payload,state,info,'running',1000,10)
        self.assertIsNone(lease);self.assertEqual(new['required_action'],'qualify_startup_readiness_before_ACP')

    def test_absent_ack_retains_observation_after_deadline_without_recreation(self):
        payload,state,_=self.inputs()
        new,lease=intent.observe(payload,state,None,'running',1000,10)
        self.assertIsNone(lease);self.assertEqual(new['stage'],'create_outcome_unknown')
        new,lease=intent.observe(payload,state,None,'failed',1000,10)
        self.assertEqual(lease,'failed');self.assertEqual(new['stage'],'create_outcome_unknown')
        self.assertIn('late_create',new['required_action'])

    def test_ownership_image_network_policy_and_environment_drift_are_not_adopted(self):
        payload,state,info=self.inputs()
        bad=[]
        changed=copy.deepcopy(info);changed['Image']='sha256:'+'c'*64;bad.append(changed)
        changed=copy.deepcopy(info);changed['Config']['Labels']['delivery-kit.owner']='other';bad.append(changed)
        changed=copy.deepcopy(info);changed['HostConfig']['ReadonlyRootfs']=False;bad.append(changed)
        changed=copy.deepcopy(info);changed['Config']['Env']=['DELIVERY_EXECUTION_MODE=review'];bad.append(changed)
        changed=copy.deepcopy(info);changed['HostConfig']['NetworkMode']='host';bad.append(changed)
        for changed in bad:
            new,lease=intent.observe(payload,state,changed,'failed',1000,10)
            self.assertEqual(new['stage'],'ownership_or_policy_conflict');self.assertIsNone(lease)
            self.assertEqual(new['required_action'],'controller_audit_no_start_or_delete')

    def test_payload_is_immutable_and_unknown_outcome_is_durable(self):
        payload,_,_=self.inputs()
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        intent.record(con,'request',payload);intent.record(con,'request',payload)
        with self.assertRaises(ValueError):intent.record(con,'request',{**payload,'User':'0:0'})
        intent.uncertain(con,'request')
        import json
        self.assertEqual(json.loads(con.execute('select state from worker_creation_intents').fetchone()[0])['stage'],'create_outcome_unknown')

    def test_start_intent_is_single_use_and_survives_unknown_ack(self):
        payload,_,_=self.inputs()
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        intent.record(con,'request',payload);intent.start_intent(con,'request');con.commit()
        with self.assertRaises(ValueError):intent.start_intent(con,'request')
        intent.start_uncertain(con,'request');con.commit()
        self.assertEqual(json.loads(con.execute('SELECT state FROM worker_creation_intents').fetchone()[0])['stage'],'start_outcome_unknown')
        with self.assertRaises(ValueError):intent.start_intent(con,'request')
        with self.assertRaises(ValueError):intent.started(con,'request')

    def test_interrupted_create_intent_is_observed_without_repost(self):
        payload,_,info=self.inputs()
        new,lease=intent.observe(payload,{'stage':'create_intent'},info,'running',1000,10)
        self.assertEqual(new['stage'],'late_container_observed');self.assertIsNone(lease)
        self.assertFalse(new['author_retry_authorized'])

    def test_docker_omitted_false_network_flag_is_not_policy_drift(self):
        payload,state,info=self.inputs()
        info['Config'].pop('NetworkDisabled')
        new,_=intent.observe(payload,state,info,'running',1000,10)
        self.assertNotEqual(new['stage'],'ownership_or_policy_conflict')
        for value in (True,None,0,'false'):
            info['Config']['NetworkDisabled']=value
            new,_=intent.observe(payload,state,info,'running',1000,10)
            self.assertEqual(new['stage'],'ownership_or_policy_conflict')
        info['Config'].pop('NetworkDisabled');payload['NetworkDisabled']=True
        new,_=intent.observe(payload,state,info,'running',1000,10)
        self.assertEqual(new['stage'],'ownership_or_policy_conflict')

    def test_start_timeout_and_restart_require_observed_running_not_just_existence(self):
        payload,_,info=self.inputs()
        for stage in ('start_intent','start_outcome_unknown'):
            for docker_status in ('created','paused','restarting'):
                info['State']['Status']=docker_status
                new,lease=intent.observe(payload,{'stage':stage},info,'running',1000,10)
                self.assertEqual(new['stage'],stage);self.assertIsNone(lease)
                self.assertEqual(new['required_action'],'observe_start_no_repost')
            info['State']['Status']='running'
            new,lease=intent.observe(payload,{'stage':stage},info,'running',1000,10)
            self.assertEqual(new['stage'],'start_running_observed');self.assertIsNone(lease)
            self.assertIn('current_capability',new['required_action'])
            self.assertFalse(new['delivery_approval']);self.assertFalse(new['author_retry_authorized'])

    def test_late_start_of_terminal_or_expired_task_never_becomes_ready(self):
        payload,_,info=self.inputs();info['State']['Status']='running'
        for native_status,deadline in [('failed',1000),('cancelled',1000),('completed',1000),('running',9)]:
            new,lease=intent.observe(payload,{'stage':'start_outcome_unknown'},info,native_status,deadline,10)
            self.assertEqual(new['stage'],'late_start_observed');self.assertEqual(lease,'failed')
            self.assertEqual(new['required_action'],'preserve_and_retire_terminal_bootstrap_container')
            self.assertFalse(new['author_retry_authorized']);self.assertFalse(new['delivery_approval'])

    def test_bootstrap_exit_is_failure_without_restart(self):
        payload,_,info=self.inputs()
        for status in ('exited','dead','removing'):
            info['State']['Status']=status
            new,lease=intent.observe(payload,{'stage':'start_intent'},info,'running',1000,10)
            self.assertEqual(new['stage'],'bootstrap_stopped');self.assertEqual(lease,'failed')
            self.assertEqual(new['required_action'],'diagnose_bootstrap_no_restart')

    def test_start_observation_revalidates_ownership(self):
        payload,_,info=self.inputs();info['State']['Status']='running';info['Image']='other'
        new,lease=intent.observe(payload,{'stage':'start_outcome_unknown'},info,'running',1000,10)
        self.assertEqual(new['stage'],'ownership_or_policy_conflict');self.assertIsNone(lease)

    def test_watchdog_observes_a_late_container_after_releasing_terminal_capacity(self):
        payload,_,info=self.inputs()
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE leases(request_id TEXT,name TEXT,status TEXT,deadline REAL)')
        con.execute("INSERT INTO leases VALUES ('request','owned','creating',0)")
        intent.record(con,'request',payload);intent.uncertain(con,'request')
        @contextmanager
        def db():
            with con:yield con
        operations=[];present=[None]
        def docker(method,path):
            operations.append((method,path));self.assertEqual(method,'GET');return present[0]
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),docker=docker,STATE='unused')
        intent.reconcile(b)
        self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0],'failed')
        self.assertEqual(json.loads(con.execute('SELECT state FROM worker_creation_intents').fetchone()[0])['stage'],'create_outcome_unknown')
        present[0]=info;intent.reconcile(b)
        result=json.loads(con.execute('SELECT state FROM worker_creation_intents').fetchone()[0])
        self.assertEqual(result['stage'],'late_container_observed');self.assertFalse(result['author_retry_authorized'])
        self.assertEqual(len(operations),2)

    def test_already_observed_create_expires_without_silent_capacity_leak(self):
        payload,state,info=self.inputs()
        new,_=intent.observe(payload,state,info,'running',1000,10)
        self.assertEqual(new['stage'],'late_container_observed')
        new,lease=intent.observe(payload,new,info,'running',1000,1001)
        self.assertEqual(lease,'failed')
        self.assertEqual(new['required_action'],'preserve_and_retire_terminal_bootstrap_container')
        self.assertFalse(new['author_retry_authorized'])
