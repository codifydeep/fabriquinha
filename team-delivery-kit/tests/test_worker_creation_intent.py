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
