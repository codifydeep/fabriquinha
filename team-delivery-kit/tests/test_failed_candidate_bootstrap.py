import copy
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import failed_candidate_bootstrap as bootstrap
from broker import failed_candidate_execution as execution


class BootstrapRepairTests(unittest.TestCase):
    def setUp(self):
        selection=dict(manifest_sha256='a'*64,product_sha256={'app.js':'b'*64},test_sha256={'test.py':'c'*64})
        self.state=dict(source_task='origin',status='blocked_technical_recovery',attempt_limit=1,
            grant_sha256='g',prior_attempts=1,prior_identical_corrections=2,
            retry_budget_reset=False,delivery_approval=False,tests_may_change=False,
            seed={'selection':selection},dispatch={'task_id':'failed','marker':'old'},
            terminal={'task_id':'failed','status':'failed','evidence_reference':'native-task:failed'},
            dispatch_marker='old',wakeup_id='old-wake')
        self.proof=dict(selection,operation='preprompt_product_fence_probe_v1',scope=['app.js'],
            actual_workspace_unchanged=True,frozen_tests_intact=True,
            delivery_approval=False,tests_executed=False,legacy_size_conflicts=['app.js'],
            product_limit=2097152,validation_job_key='job',output_sha256='d'*64)

    def test_preserves_failure_and_counters_once_with_distinct_dispatch_origin(self):
        before=copy.deepcopy(self.state)
        repaired=bootstrap.prepare(self.state,'failed','request',self.proof)
        self.assertEqual(self.state,before)
        self.assertEqual(repaired['bootstrap_recovery']['previous_terminal'],before['terminal'])
        self.assertEqual(repaired['bootstrap_recovery']['previous_dispatch'],before['dispatch'])
        for k in ('grant_sha256','source_task','prior_attempts','prior_identical_corrections','attempt_limit','seed'):
            self.assertEqual(repaired[k],before[k])
        self.assertFalse(repaired['retry_budget_reset'])
        self.assertFalse(repaired['delivery_approval'])
        self.assertFalse(repaired['tests_may_change'])
        self.assertEqual(repaired['status'],'admitted_not_dispatched')
        self.assertEqual(execution.dispatch_source(repaired),'failed')
        self.assertEqual(execution.dispatch_source(before),'origin')
        self.assertEqual(bootstrap.prepare(repaired,'failed','request',self.proof),repaired)
        with self.assertRaises(ValueError):bootstrap.prepare(repaired,'second','request',self.proof)
        with self.assertRaises(ValueError):bootstrap.prepare(repaired,'failed','another',self.proof)
        with self.assertRaises(ValueError):bootstrap.prepare(repaired,'failed','request',{**self.proof,'output_sha256':'z'})

    def test_rejects_modified_workspace_tests_unexecuted_proof_or_nonbootstrap(self):
        for patch in ({'actual_workspace_unchanged':False},{'frozen_tests_intact':False},
                      {'delivery_approval':True},{'tests_executed':True},{'legacy_size_conflicts':[]},
                      {'validation_job_key':None},{'product_sha256':{'app.js':'0'*64}},
                      {'test_sha256':{'test.py':'0'*64}},{'scope':['app.js','test.py']}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                bootstrap.prepare(self.state,'failed','request',{**self.proof,**patch})
        with self.assertRaises(ValueError):
            bootstrap.prepare({**self.state,'status':'execution_bound'},'failed','request',self.proof)

    def test_qualification_rejects_any_prompt_event_or_tool_and_uses_fixed_isolated_job(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        self.addCleanup(con.close)
        con.executescript('''CREATE TABLE native_bindings(request_id,task_id,agent_id,scope,issue_id);
            CREATE TABLE leases(request_id,status);
            CREATE TABLE acp_startups(request_id,state);
            CREATE TABLE broker_errors(request_id,operation,category);
            CREATE TABLE acp_events(request_id,method);
            CREATE TABLE tool_events(request_id,tool_count);
            CREATE TABLE delivery_handoffs(source_task,data);
            CREATE TABLE worker_creation_intents(request_id,payload);''')
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',('request','failed','author','scope','issue'))
        con.execute('INSERT INTO leases VALUES(?,?)',('request','closed'))
        con.execute('INSERT INTO acp_startups VALUES(?,?)',('request',json.dumps(dict(stage='failed',category='startup_broker_internal'))))
        con.execute('INSERT INTO broker_errors VALUES(?,?,?)',('request','transport_start','bootstrap:broker_internal'))
        original=dict(failed_candidate_execution={'grant_sha256':'g'},failed_candidate_plan={'x':1},failed_candidate_plan_review={'y':2})
        con.execute('INSERT INTO delivery_handoffs VALUES(?,?)',('origin',json.dumps(original)))
        con.execute('INSERT INTO worker_creation_intents VALUES(?,?)',('request',json.dumps({'Image':bootstrap.LEGACY_WORKER_IMAGE})))
        state={**self.state,'author':'author','contract_sha256':'contract',
            'plan_sha256':execution.digest(original['failed_candidate_plan']),
            'review_sha256':execution.digest(original['failed_candidate_plan_review']),
            'seed':{**self.state['seed'],'mount':dict(Type='volume',Source='snapshot',Target='/previous',ReadOnly=True)}}
        route=dict(issue_id='issue',author='author',contract_sha256='contract')
        b=SimpleNamespace(IMAGE='sha256:'+'9'*64,PREFIX='delivery-kit-unit',OWNER='owner',
            docker=lambda *_:{'Labels':{'delivery-kit.owner':'owner','delivery-kit.scope':'scope'}},
            handoff_runtime=SimpleNamespace(task_base=lambda *_:dict(volume='base',manifest_sha256='m')))
        runs=[dict(id='failed',agent_id='author',status='failed',wakeup_id='old-wake',
            error='hermes initialize failed: hermes process exited')]
        output=json.dumps(self.proof)
        result=dict(exit_code=0,output=output,output_sha256=bootstrap.hashlib.sha256(output.encode()).hexdigest(),validation_job_key='job')
        with patch.object(bootstrap.native,'issue_task_runs',return_value=runs),\
                patch.object(bootstrap.bound_failure_context,'verified_failed_diagnostic',return_value=True),\
                patch.object(bootstrap.validation_job,'run',return_value=result) as run:
            bootstrap.qualify(b,con,route,{},state,{})
            payload=run.call_args.args[3]
            self.assertEqual(payload['Cmd'],['/bootstrap_fence_probe.py'])
            self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
            self.assertTrue(payload['HostConfig']['ReadonlyRootfs'])
            self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))
            self.assertEqual(set(payload['HostConfig']['Tmpfs']),{'/workspace'})
            self.assertNotIn('Binds',payload['HostConfig'])
            run.reset_mock()
            con.execute('INSERT INTO acp_events VALUES(?,?)',('request','session/prompt'))
            with self.assertRaisesRegex(ValueError,'no ACP event'):bootstrap.qualify(b,con,route,{},state,{})
            run.assert_not_called()
            con.execute('DELETE FROM acp_events')
            con.execute('INSERT INTO tool_events VALUES(?,?)',('request',0))
            with self.assertRaisesRegex(ValueError,'no ACP event'):bootstrap.qualify(b,con,route,{},state,{})
            run.assert_not_called()


if __name__=='__main__':unittest.main()
