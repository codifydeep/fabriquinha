"""Controller/native/read fixtures, not real-agent qualification."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from broker import quality_delivery_review_attestation as attest,worker_creation_intent as worker
import test_quality_delivery_review_launch as fixtures


class DeliveryAttestationTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryReviewLaunchTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.request=f.request;self.native=f.f.f.current
        c,assignment,validation=attest.launch.context_for(self.b,self.request)
        self.c=c;self.assignment=assignment
        p=attest.launch.payload(self.b,self.request)
        info=dict(Id='4'*64,Image=p['Image'],State=dict(Status='running'),
            Config={k:copy.deepcopy(v) for k,v in p.items() if k not in ('HostConfig','Image')},HostConfig=copy.deepcopy(p['HostConfig']))
        with self.b.db() as con:
            con.execute('UPDATE grants SET used=1 WHERE request_id=?',(self.request,))
            con.execute('INSERT INTO leases VALUES(?,?,?,?,?)',(self.request,'acp-session',self.b.PREFIX+'-job-'+self.request,'closed',9999999999))
            worker.record(con,self.request,p);worker.record_observation(con,self.request,p,info)
            con.execute('CREATE TABLE IF NOT EXISTS quality_transport_intents(request_id TEXT PRIMARY KEY,state TEXT)')
            con.execute('INSERT INTO quality_transport_intents VALUES(?,?)',(self.request,'opened'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(self.request,method,'delivery-session',1))
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(c['scope'],'delivery-session'))
        # Locate the existing byte fixtures, not fabricated read hashes.
        obj=f;source=None
        for _ in range(16):
            if hasattr(obj,'files') and isinstance(obj.files,dict):source=obj.files;break
            obj=getattr(obj,'f',None)
            if obj is None:break
        self.assertIsNotNone(source);self.files={**source,'app.py':b'VALUE=1\n'}
        self.assertEqual({p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in self.files.items()},assignment['file_inventory'])
        frames=[]
        for n,(path,raw) in enumerate(self.files.items()):
            lines=raw.decode().splitlines();body='\n'.join(str(i)+'|'+line for i,line in enumerate(lines,1))
            frames.extend([dict(method='session/update',params=dict(update=v)) for v in (
                dict(sessionUpdate='tool_call',toolCallId='delivery-read-'+str(n),kind='read',title='read: /delivery/'+path),
                dict(sessionUpdate='tool_call_update',toolCallId='delivery-read-'+str(n),status='completed',
                    content=[dict(type='content',content=dict(type='text',text=f'Read /delivery/{path} (from line 1, limit 100) — {len(lines)} total lines\n\n```\n{body}\n```'))]))])
        with self.b.db() as con:attest.stream.store(con,c,frames,'review')
        self.value=dict(action='approve_delivery',reason='Exact candidate meets the acceptance criteria',
            manifest_sha256=c['manifest_sha256'],commit_sha=c['commit_sha'],plan_sha256=attest.quality.digest(assignment['plan']),
            quality_evidence_sha256=attest.quality.digest(assignment['evidence']),validation_sha256=attest.quality.digest(validation['validation']),
            criteria=list(assignment['plan']['criteria']),findings=[])
        self.native.update(status='completed');self.update()

    def update(self,**changes):
        self.value.update(changes);self.native['result']=dict(output=json.dumps(self.value))

    def call(self):return attest.observe(self.b,self.request)

    def test_native_completed_exact_snapshot_and_bound_stream_yield_only_review_facts(self):
        result=self.call();self.assertEqual(result['stage'],'delivery_reviewed')
        self.assertEqual(result['commit_sha'],self.c['commit_sha']);self.assertEqual(len(result['reads']),len(self.files))
        self.assertFalse(result['merge_authorized']);self.assertFalse(result['delivery_approval'])
        with patch.object(attest.review.native,'task_record',side_effect=AssertionError('no native replay')):
            self.assertEqual(self.call(),result)

    def test_ui_claims_or_old_read_stream_cannot_replace_reviewer_reads(self):
        with self.b.db() as con:con.execute('DELETE FROM observed_read_stream WHERE task_id=?',(self.c['task_id'],))
        self.assertEqual(self.call()['stage'],'technical_blocked')

    def test_worker_policy_or_transport_proofs_are_mandatory(self):
        with self.b.db() as con:con.execute('DELETE FROM worker_policy_observations WHERE request_id=?',(self.request,))
        result=self.call();self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],self.assignment['cto'])

    def test_running_task_and_unclosed_lease_wait_for_same_execution(self):
        self.native['status']='running'
        with self.assertRaises(attest.validation_job.Pending):self.call()
        self.native['status']='completed'
        with self.b.db() as con:con.execute("UPDATE leases SET status='closing' WHERE request_id=?",(self.request,))
        with self.assertRaises(attest.validation_job.Pending):self.call()

    def test_wait_deadline_does_not_reset_and_expires_to_cto_without_retry(self):
        self.native['status']='running'
        with patch.object(attest.time,'time',return_value=1000),self.assertRaises(attest.validation_job.Pending):self.call()
        with patch.object(attest.time,'time',return_value=2801):result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertFalse(result['incident']['automatic_retry'])
        self.assertEqual(result['owner'],self.assignment['cto'])

    def test_changes_address_original_author_and_preserve_exact_candidate(self):
        finding=dict(criterion=self.assignment['plan']['criteria'][0],path='app.py',line=1,quote='VALUE=1',
            expected='A complete product behavior',observed='Only a constant in this synthetic fixture')
        self.update(action='request_changes',findings=[finding]);result=self.call()
        self.assertEqual(result['stage'],'changes_requested');self.assertEqual(result['owner'],self.assignment['author'])
        self.assertEqual(result['implementation_request'],self.c['implementation_request']);self.assertFalse(result['execution_authorized'])

    def test_stale_verdict_or_native_identity_never_approve_candidate(self):
        self.update(validation_sha256='0'*64);result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertFalse(result['merge_authorized'])

    def test_foreign_wakeup_is_a_cto_incident_not_a_ceo_question(self):
        self.native['wakeup_id']='foreign-wakeup';result=self.call()
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],self.assignment['cto'])
        self.assertEqual(result['incident']['category'],'delivery_review_native_identity')

    def test_receipt_readback_rejects_changed_validation_job(self):
        self.call()
        with self.b.db() as con:con.execute("DELETE FROM validation_jobs WHERE json_extract(identity,'$.kind')='delivery_review'")
        with self.assertRaises(ValueError):attest.load(self.b,self.request)

    def test_maintenance_preserves_evidence_without_creating_attestation(self):
        with self.b.db() as con:con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operator','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(attest.validation_job.Pending):self.call()
        with self.b.db() as con:self.assertIsNone(con.execute('SELECT 1 FROM quality_delivery_review_attestations').fetchone())


if __name__=='__main__':unittest.main()
