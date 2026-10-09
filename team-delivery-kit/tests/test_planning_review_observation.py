import copy
import json
import unittest
from broker import planning_review_observation as module
from broker.technical_remediation_plan import digest


class PlanningReviewObservationTests(unittest.TestCase):
    def test_runtime_observes_pending_job_then_records_one_independent_review(self):
        import sqlite3,threading,tempfile
        from contextlib import contextmanager
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);con.row_factory=sqlite3.Row
        module.plans.initialize(con)
        con.executescript('CREATE TABLE leases(request_id,status);CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id);CREATE TABLE broker_errors(request_id,operation,category);CREATE TABLE acp_events(request_id);')
        task_id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        con.execute("INSERT INTO leases VALUES('request','expired')")
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?)',('request',task_id,'lead','issue'))
        con.execute("INSERT INTO broker_errors VALUES('request','/v1/acp-message','prompt_timeout')")
        config=dict(cto='cto',reviewer='lead',criteria={'A01':'unchanged'},required_paths=['/evidence/test.py'])
        plan=dict(action='propose_remediation_plan',evidence_sha256=digest(config),reason='Scoped plan',execution_authorized=False,release_homologated=False,
            steps=[dict(id='R'+str(i),depends_on=[] if i==1 else ['R'+str(i-1)],edit_scope=scope,objective='Preserve gates',criteria=['A01'])
                for i,scope in enumerate(('new_tests_only','product_only','controller_only'),1)])
        state={**self.state,'plan':plan,'plan_sha256':digest(plan),'plan_task':'original','plan_wakeup':'original-wake'}
        con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',('source',json.dumps(config),json.dumps(state)))
        original=dict(id='original',status='completed',agent_id='cto',issue_id='issue',wakeup_id='original-wake')
        failed={**self.task,'id':task_id}
        fx=SimpleNamespace(settings={},task=lambda tid,agent:original if tid=='original' else failed,
            result=lambda t:plan,reads=lambda t:{} if t['id']==task_id else {'/evidence/test.py':dict(lines=2,total_lines=2)})
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),IMAGE='sha256:worker')
        with tempfile.TemporaryDirectory() as folder:
            program=Path(folder)/'probe.py';program.write_text('fixed-controller-probe')
            with patch.object(module,'Path',return_value=program),patch.object(module.plans,'Effects',return_value=fx),patch.object(module.plans.native,'issue_task_runs',return_value=[failed]),patch.object(module.test_first_job,'run',side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):module.reconcile(b,'source')
            self.assertEqual(json.loads(con.execute('SELECT state FROM technical_remediation_plans').fetchone()[0]),state)
            result=dict(exit_code=0,output=json.dumps(self.probe),output_sha256='output-hash',container_id='probe-container')
            with patch.object(module,'Path',return_value=program),patch.object(module.plans,'Effects',return_value=fx),patch.object(module.plans.native,'issue_task_runs',return_value=[failed]),patch.object(module.test_first_job,'run',return_value=result) as run:
                recovered=module.reconcile(b,'source')
                self.assertEqual(recovered['stage'],'review_dispatch')
                self.assertEqual(module.reconcile(b,'source'),recovered)
                self.assertEqual(run.call_count,1)
                payload=run.call_args.args[-1]
                self.assertIn("sys.path.insert(0,'/')",payload['Cmd'][1])
                self.assertIn("assert importlib.util.find_spec('acp_transport') is None",payload['Cmd'][1])
                self.assertIn("assert importlib.util.find_spec('acp_transport') is not None",payload['Cmd'][1])
                self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
                self.assertNotIn('Mounts',payload['HostConfig'])
                self.assertEqual(recovered['planning_review_observation']['previous'],state)
            # A failed immutable old launch is retained, not overwritten. The
            # changed experiment gets one stable distinct job identity.
            con.execute('UPDATE technical_remediation_plans SET state=?',(json.dumps(state),))
            old_payload={**payload,'Cmd':['-c',program.read_text()]}
            identity=dict(name='old-job',payload=old_payload)
            old_result=dict(exit_code=1,container_id='retired-original',output='',output_sha256='old-output')
            old_job=dict(stage='complete',result=old_result)
            con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',(task_id+':copy',json.dumps(identity),json.dumps(old_job)))
            b.docker=lambda *args:None
            with patch.object(module,'Path',return_value=program),patch.object(module.plans,'Effects',return_value=fx),patch.object(module.plans.native,'issue_task_runs',return_value=[failed]),patch.object(module.test_first_job,'run',side_effect=[old_result,result]) as run:
                repaired=module.reconcile(b,'source')
                self.assertEqual(run.call_count,2)
                self.assertNotEqual(run.call_args_list[0].args[2],run.call_args_list[1].args[2])
                self.assertEqual(repaired['planning_review_probe_import_repair']['historical_probe_cause'],'unknown')
                self.assertEqual(repaired['planning_review_probe_import_repair']['attempt_limit'],1)
                self.assertEqual(module.reconcile(b,'source'),repaired)
            self.assertEqual(json.loads(con.execute('SELECT state FROM test_first_jobs WHERE job_key=?',(task_id+':copy',)).fetchone()[0]),old_job)

    def setUp(self):
        self.config=dict(cto='cto',reviewer='lead')
        self.plan={'exact':'original proposal'}
        self.state=dict(stage='blocked',category='ValueError',plan=self.plan,plan_sha256=digest(self.plan),
            issue_id='issue',wakeup_id='wake',execution_authorized=False)
        self.task=dict(id='failed',status='failed',agent_id='lead',issue_id='issue',wakeup_id='wake')
        self.failure=dict(category='prompt_timeout',event_count=0,lease_status='expired')
        self.probe=dict(schema='real-acp-initialize-probe-v1',status='passed',actual_hermes_initialize=True,
            prompts_sent=0,sessions_created=0,network='none',socket_absent=True,delivery_approval=False)

    def prepare(self,**changes):
        values=dict(config=self.config,state=self.state,task=self.task,reads={},failure=self.failure,probe=self.probe)
        values.update(changes)
        return module.prepare(**values)

    def test_one_observation_preserves_exact_plan_and_unknown_cause(self):
        before=copy.deepcopy(self.state)
        new=self.prepare()
        self.assertEqual(self.state,before)
        self.assertEqual(new['stage'],'review_dispatch')
        self.assertEqual(new['owner'],'lead')
        proof=new['planning_review_observation']
        self.assertEqual(proof['previous'],before)
        self.assertEqual(proof['cause'],'unknown')
        self.assertEqual(proof['attempt_limit'],1)
        self.assertFalse(proof['delivery_approval'])
        self.assertNotIn('wakeup_id',new)
        self.assertNotIn('review',new)
        with self.assertRaises(ValueError):self.prepare(state={**new,'stage':'blocked','category':'ValueError'})

    def test_foreign_partial_approved_or_live_execution_never_recovers(self):
        cases=[('state',dict(plan_sha256='foreign')),('state',dict(review_task='approved')),
            ('state',dict(execution_authorized=True)),('task',dict(agent_id='cto')),
            ('task',dict(wakeup_id='foreign')),('task',dict(status='running')),
            ('failure',dict(lease_status='running')),('failure',dict(event_count=1)),
            ('failure',dict(category='worker_io')),('probe',dict(prompts_sent=1)),
            ('probe',dict(network='api')),('probe',dict(delivery_approval=True)),
            ('probe',dict(socket_absent=False)),('probe',dict(status='failed'))]
        for field,change in cases:
            with self.subTest(field=field,change=change),self.assertRaises(ValueError):
                self.prepare(**{field:{**getattr(self,field),**change}})
        with self.assertRaises(ValueError):self.prepare(reads={'/evidence/candidate/test.py':{'lines':1}})
