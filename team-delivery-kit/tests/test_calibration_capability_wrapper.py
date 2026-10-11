import copy
import hashlib
import json
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from broker import generic_calibration_capability_recovery as recovery,generic_calibration_workflow as workflow,handoffs
from broker import controller_maintenance as maintenance,generic_calibration_seam_job as jobs
import test_generic_calibration_proposal_collector as samples


class CapabilityWrapperTests(unittest.TestCase):
    def setUp(self):
        f=samples.ProposalCollectorTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.con=f.con;self.b=f.b
        self.issue='00000000-0000-4000-8000-000000000001';self.author='00000000-0000-4000-8000-000000000002'
        self.operation='00000000-0000-4000-8000-000000000003'
        self.barrier=dict(operation_id=self.operation,stage='sealed',namespace=self.b.PREFIX,drained=True)
        self.con.execute('UPDATE delivery_routes SET issue_id=?',(self.issue,))
        self.con.execute('UPDATE native_bindings SET issue_id=?',(self.issue,))
        self.con.execute('UPDATE native_bindings SET task_id=?,scope=? WHERE agent_id=?',
            (self.author,'workspace:author:implementation:'+self.author,'author'))
        row=self.con.execute('SELECT identity,state FROM test_first_jobs').fetchone();identity,state=map(json.loads,row)
        identity['payload']['Labels']['delivery-kit.test-first-task']=self.author
        self.con.execute('UPDATE test_first_jobs SET job_key=?,identity=?',(self.author+':copy',json.dumps(identity)))
        workflow.initialize(self.con);handoffs.initialize(self.con)
        self.c=dict(issue_id=self.issue,author_task=self.author,cto='cto',reviewer='lead',
            candidate_volume='delivery-kit-port2-candidate',prepared=f.fixture.prepared)
        self.state=dict(stage='blocked',category='bundle_task_failed',observed_task='cto-task',wakeup_id='wake',
            execution_authorized=False,delivery_approval=False)
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            (self.issue,self.author,json.dumps(self.c),json.dumps(self.state)))
        handoffs.save(self.con,self.author,self.issue,'test_first_blocked','cto',
            dict(calibration_prerequisite=self.state,error='generic_calibration_prerequisite:bundle_task_failed'),0)
        path=next(iter(self.c['prepared']['test_sha256']))
        self.proof=dict(operation='generic_calibration_multipath_seam_v1',candidate_manifest_sha256=self.c['prepared']['manifest_sha256'],
            test_sha256=self.c['prepared']['test_sha256'],paths={path:{'APP_JS':'app/app.js','INDEX_HTML':'app/index.html'}},
            product_sha256={'app/app.js':'e'*64,'app/index.html':'f'*64},tests_executed=False,execution_authorized=False,delivery_approval=False)
        raw=json.dumps(self.proof)
        self.result=dict(container_id='probe',exit_code=0,approval=False,output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.author_task=dict(id=self.author,agent_id='author',workspace_id='workspace',chat_session_id=self.author,
            issue_id=self.issue,status='completed')
        self.task=dict(id='cto-task',agent_id='cto',issue_id=self.issue,status='failed',wakeup_id='wake')
        self.fx=SimpleNamespace(verify=lambda c:None,plans=SimpleNamespace(task=lambda tid,actor:
            self.author_task if actor=='author' else self.task))

    def migrate(self,probe_error=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(maintenance,'native_active',return_value=[]))
            stack.enter_context(patch.object(maintenance,'current',return_value=self.barrier))
            stack.enter_context(patch.object(workflow,'Effects',return_value=self.fx))
            stack.enter_context(patch.object(jobs,'payload',return_value={'Image':'sha256:'+'a'*64}))
            self.probe=stack.enter_context(patch.object(jobs,'run',return_value=self.result,side_effect=probe_error))
            return recovery.migrate(self.b,self.issue,self.author,self.operation)

    def test_authenticated_real_record_path_preserves_probe_identity_and_never_repeats(self):
        receipt=self.migrate();self.assertEqual(receipt['probe_evidence']['container_id'],'probe')
        self.assertEqual(self.probe.call_count,1);self.assertFalse(receipt['author_restarted'])
        self.assertEqual(self.migrate(),receipt);self.assertEqual(self.probe.call_count,0)

    def test_unsealed_wrong_identity_or_active_binding_never_starts_probe(self):
        for mutate,reset in ((lambda:self.barrier.update(stage='released'),lambda:self.barrier.update(stage='sealed')),
                (lambda:self.task.update(agent_id='foreign'),lambda:self.task.update(agent_id='cto')),
                (lambda:self.con.execute("UPDATE leases SET status='running' WHERE request_id='cto'"),
                    lambda:self.con.execute("UPDATE leases SET status='closed' WHERE request_id='cto'"))):
            mutate();self.con.commit()
            with self.assertRaises(ValueError):self.migrate()
            self.assertEqual(self.probe.call_count,0);reset();self.con.commit()

    def test_pending_probe_does_not_transfer_responsibility_or_migrate(self):
        with self.assertRaises(TimeoutError):self.migrate(TimeoutError('observe same handle'))
        row=self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone()
        self.assertEqual(list(map(json.loads,row)),[self.c,self.state])
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_capability_recoveries').fetchone()[0],0)
        self.assertEqual(handoffs.load(self.con,self.author)['stage'],'test_first_blocked')
