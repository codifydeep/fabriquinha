import copy
import contextlib
import hashlib
import json
import os
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import literal_diagnosis_evidence as evidence
from broker import literal_maintenance_workflow as flow


class DiagnosisEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(source=dict(author_task='original-task',candidate_volume='original-volume',prepared=dict(manifest_sha256='a'*64)),
            workflow_key='rejected-author',test_path='tests/test.py',author='author',cto='cto',reviewer='lead',
            feedback_strategy=dict(policy=dict(source_task='rejected-author',previous_volume='seed-volume',previous_manifest_sha256='b'*64)))
        self.s=dict(stage='blocked',category='maintenance_evidence_rejected',last_error=dict(phase='diagnose_wait',type='ValueError'),
            history=[dict(unchanged='rejection')],revision=0,issue_id='maintenance',wakeup_id='old-wake',
            author_task='current-author',snapshot=dict(volume='candidate-volume'),inspection=dict(candidate_manifest_sha256='c'*64))
        self.s['cto_escalation']=flow.escalation_binding(self.cfg,self.s)
        note='READ ONLY\n'+''.join('DELIVERY_REVIEW_READ_PATH:/evidence/'+root+'/tests/test.py\n' for root in ('candidate','previous','seed'))
        self.s['marker']=flow.digest(dict(config=self.cfg,phase='diagnose',instruction=note,revision=0))
        self.task=dict(id='old-task',status='completed',agent_id='cto',issue_id='maintenance',wakeup_id='old-wake',
            handoff_note='DELIVERY_PLANNING_START '+self.s['marker']+'\nSource: rejected-author\n'+note.strip(),
            result=dict(output='{"action":"request_test_revision"}'))
        self.reads={'/evidence/'+root+'/tests/test.py':dict(lines=10,total_lines=10) for root in ('candidate','previous')}

    def test_only_exact_missing_third_read_can_qualify_a_fresh_diagnostic(self):
        proof=evidence.failed_read_proof(self.cfg,self.s,self.task,self.reads)
        self.assertEqual(proof['failure'],'third_root_not_supported');self.assertFalse(proof['decision_accepted'])
        for change in (dict(agent_id='lead'),dict(status='running'),dict(wakeup_id='other'),dict(handoff_note='forged')):
            with self.assertRaises(ValueError):evidence.failed_read_proof(self.cfg,self.s,dict(self.task,**change),self.reads)
        for bad in ({},dict(self.reads,**{'/evidence/seed/tests/test.py':dict(lines=10,total_lines=10)})):
            with self.assertRaises(ValueError):evidence.failed_read_proof(self.cfg,self.s,self.task,bad)
        changed=copy.deepcopy(self.s);changed['history'][0]['unchanged']='altered'
        with self.assertRaises(ValueError):evidence.failed_read_proof(self.cfg,changed,self.task,self.reads)

    def test_bundle_payload_has_no_network_commands_secrets_or_writable_source_mounts(self):
        with patch.dict(os.environ,BROKER_LITERAL_DIAGNOSIS_BUNDLE_IMAGE='sha256:'+'d'*64):ident=evidence.identity(self.cfg,self.s)
        body=evidence.payload(ident,'bundle-volume',{'owner':'test'})
        self.assertEqual(body['User'],'10000:10000');self.assertEqual(body['HostConfig']['CapDrop'],['ALL'])
        self.assertEqual(body['HostConfig']['NetworkMode'],'none');self.assertTrue(body['HostConfig']['ReadonlyRootfs'])
        self.assertTrue(all(m['ReadOnly'] for m in body['HostConfig']['Mounts'][:-1]))
        self.assertEqual(body['Cmd'][0],'/literal_diagnosis_bundle.py');self.assertFalse(body['HostConfig']['Mounts'][-1]['ReadOnly'])
        verified=evidence.payload(ident,'bundle-volume',{'owner':'test'},'verify')
        self.assertTrue(all(m['ReadOnly'] for m in verified['HostConfig']['Mounts']))
        self.assertEqual(set(body['Env']),{'PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'})

    def test_lost_volume_create_ack_is_observed_not_repeated(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);volumes={};creates=[]
        def docker(method,path,payload=None):
            if method=='GET':return volumes.get(path.split('/')[-1])
            creates.append(payload);volumes[payload['Name']]=dict(Labels=payload['Labels']);raise TimeoutError()
        b=SimpleNamespace(db=lambda:con,PREFIX='delivery-kit-test',OWNER='owned',docker=docker)
        with patch.dict(os.environ,BROKER_LITERAL_DIAGNOSIS_BUNDLE_IMAGE='sha256:'+'d'*64):
            with self.assertRaises(TimeoutError):evidence.prepare(b,self.cfg,self.s)
            report=dict(source_manifests={k:v['manifest'] for k,v in evidence.identity(self.cfg,self.s)['sources'].items()})
            output=json.dumps(dict(operation='literal_diagnosis_bundle_v1',source_unchanged=True,source_reset=False,
                delivery_approval=False,model_calls=0,report=report,manifest_sha256='e'*64))
            job=dict(exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest())
            with patch.object(evidence.validation_job,'run',return_value=job):
                first=evidence.prepare(b,self.cfg,self.s);self.assertEqual(first,evidence.prepare(b,self.cfg,self.s))
                self.assertEqual(len(creates),1)
                altered=dict(first,manifest_sha256='f'*64)
                with self.assertRaises(ValueError):evidence.validate(b,self.cfg,self.s,altered)

    def test_sealed_recovery_preserves_failed_state_and_is_idempotent_without_task_replay(self):
        from broker import literal_maintenance_effects as lane
        import recover_literal_diagnosis_reads as cli
        compile(cli.PROGRAM,'diagnosis-recovery-cli','exec')
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);flow.initialize(con)
        con.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',
            ('rejected-author',json.dumps(self.cfg),json.dumps(self.s)))
        con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        con.execute("INSERT INTO leases VALUES('request','closed')");con.commit()
        b=SimpleNamespace(db=lambda:con,LOCK=contextlib.nullcontext())
        fx=SimpleNamespace(verify=lambda cfg:None,runs=lambda cfg,s:[self.task],
            plans=SimpleNamespace(task=lambda *args:self.task,reads=lambda task:self.reads),
            old=SimpleNamespace(binding=lambda *args:dict(request_id='request')))
        with patch.object(evidence.maintenance,'current',return_value=dict(stage='sealed',operation_id='op')),\
                patch.object(evidence.maintenance,'native_active',return_value=False),patch.object(lane,'Effects',return_value=fx),\
                patch.object(flow,'authenticate'),patch.object(flow,'authenticate_rejections'):
            r=evidence.recover(b,'rejected-author','op');again=evidence.recover(b,'rejected-author','op')
        self.assertEqual(r,again);self.assertEqual(r['previous_state'],self.s)
        self.assertFalse(r['author_retry_authorized']);self.assertFalse(r['delivery_approval'])
        state=json.loads(con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()[0])
        self.assertEqual(state['stage'],'diagnosis_bundle');self.assertEqual(state['history'],self.s['history'])
        self.assertEqual(state['revision'],self.s['revision']);self.assertEqual(state['wakeup_id'],'old-wake')
        self.assertEqual(con.execute('SELECT count(*) FROM literal_diagnosis_read_recoveries').fetchone()[0],1)
