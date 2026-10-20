from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
from broker import author_feedback_admission as admission


def identity(n):return '00000000-0000-4000-8000-'+str(n).zfill(12)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);root=Path(folder.name)
        self.tasks={};self.source,self.issue,self.author,self.cto,self.lead=[identity(n) for n in range(1,6)]
        self.settings=dict(agents={self.author:'implementation',self.cto:'planning',self.lead:'planning'})
        (root/'native.json').write_text(json.dumps(self.settings))
        @contextmanager
        def db():
            c=sqlite3.connect(root/'state.sqlite');c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        self.db=db;self.b=SimpleNamespace(STATE=root,db=db,LOCK=threading.RLock(),PREFIX='delivery-kit-test',OWNER='owner')
        self.q=dict(operation='qualified_author_feedback_worker_v1',native_execution=False,delivery_approval=False,
            identity=dict(image='sha256:'+'c'*64,source_sha256={k:'a'*64 for k in ('client','policy','formatter','wire')}))
        self.q['proof']=dict(operation='author_feedback_real_registry_canary_v1',status='passed',uid=10000,network='none',
            model_calls=0,controller_transport_stubbed=True,native_execution=False,delivery_approval=False,
            full_regression_suite_executed=False,source_sha256=self.q['identity']['source_sha256'],**{k:True for k in admission.FLAGS})
        self.p=dict(source_task=self.source,issue_id=self.issue,author=self.author,cto=self.cto,reviewer=self.lead,
            previous_volume='delivery-kit-test-snapshot-'+self.source,previous_manifest_sha256='b'*64,
            test_path='tests/test.py',image='sha256:'+'d'*64,worker_image=self.q['identity']['image'],
            feedback_sha256='e'*64,qualification_sha256=admission.digest(self.q),max_candidates=4,
            expected=dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11'))
        with db() as c:
            c.executescript('CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id,scope);'
                'CREATE TABLE grants(request_id,task_id,mode,used,attempt,deadline);CREATE TABLE leases(request_id,status);'
                'CREATE TABLE snapshots(task_id,volume,status);CREATE TABLE tool_events(request_id,tool_count);')
            c.execute('INSERT INTO snapshots VALUES(?,?,?)',(self.source,self.p['previous_volume'],'complete'))
        self.b.docker=lambda method,path:(dict(Id=path[len('/images/'):-len('/json')]) if path.startswith('/images/') else
            None if path.startswith('/containers/') else dict(Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':self.source}))
        for name,value in [('task_record',self.task_record),('issue_task_runs',lambda *args:copy.deepcopy(list(self.tasks.values())))]:
            mock=patch.object(admission.native,name,side_effect=value);mock.start();self.addCleanup(mock.stop)
        self.approvals=dict(cto=identity(10),sponsor=identity(11))
        self.add_planner('cto',self.approvals['cto'],self.cto)
        proposal=admission.approval(self.b,self.p,'cto',self.approvals['cto'])
        self.add_planner('sponsor',self.approvals['sponsor'],self.lead,proposal)

    def task_record(self,settings,task,actor):
        result=self.tasks.get(task,{})
        self.assertEqual(result.get('agent_id'),actor)
        return copy.deepcopy(result)

    def add_planner(self,phase,task,actor,proposal=None):
        value=dict(admission.context(self.p),action='refer_to_cto',reason='Qualified feedback changes evidence, not acceptance',
            author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
        self.tasks[task]=dict(id=task,agent_id=actor,issue_id=self.issue,status='completed',wakeup_id=identity(20 if phase=='cto' else 21),
            handoff_note=admission.note(self.p,phase,proposal),result=dict(output=json.dumps(value,sort_keys=True)))
        self.bind(task,actor,task,'planning','closed')

    def bind(self,request,actor,task,mode,status,attempt=1):
        with self.db() as c:
            c.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(request,task,actor,self.issue,'workspace:'+mode+':'+task))
            c.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)',(request,task,mode,1,attempt,time.time()+300))
            c.execute('INSERT INTO leases VALUES(?,?)',(request,status))

    def arm(self):return admission.arm(self.b,self.p,self.q,self.approvals)

    def start(self):
        self.task=identity(30);self.request=identity(31)
        self.tasks[self.task]=dict(id=self.task,agent_id=self.author,issue_id=self.issue,status='running',
            wakeup_id=identity(32),handoff_note=admission.note(self.p,'author'))
        self.bind(self.request,self.author,self.task,'implementation','creating')

    def test_exact_native_handoff_claimed_once_without_issuing_rpc_capability(self):
        state=self.arm();self.assertEqual(state['stage'],'armed');self.start()
        selected=admission.select(self.b,self.request,self.issue)
        self.assertEqual(selected['worker_image'],self.p['worker_image']);self.assertEqual(selected['task_id'],self.task)
        self.assertEqual(selected['note_sha256'],hashlib.sha256(admission.note(self.p,'author').encode()).hexdigest())
        self.assertEqual(admission.select(self.b,self.request,self.issue),selected)
        with self.db() as c:
            state=json.loads(c.execute('SELECT state FROM author_feedback_admissions').fetchone()[0])
            self.assertEqual(state['request_id'],self.request)
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='author_feedback_capabilities'").fetchone())
        self.assertEqual(self.arm(),state)  # Re-registration does not reset consumed state.

    def test_wakeup_old_actor_other_issue_or_changed_note_cannot_claim(self):
        self.arm();self.start();original=copy.deepcopy(self.tasks[self.task])
        for change in [dict(status='completed'),dict(agent_id=self.lead),dict(issue_id=identity(99)),dict(handoff_note=original['handoff_note']+' altered')]:
            self.tasks[self.task]={**original,**change}
            with self.assertRaises((ValueError,AssertionError)):admission.select(self.b,self.request,self.issue)
        self.tasks[self.task]=original
        self.assertIsNone(admission.select(self.b,self.request,identity(99)))

    def test_reviewer_execution_receives_no_author_policy(self):
        self.arm();request=identity(50);self.bind(request,self.lead,identity(51),'review','running')
        self.assertIsNone(admission.select(self.b,request,self.issue))

    def test_duplicate_task_or_second_execution_is_rejected_without_reset(self):
        self.arm();self.start();first=admission.select(self.b,self.request,self.issue)
        self.tasks[identity(70)]={**self.tasks[self.task],'id':identity(70)}
        with self.assertRaises(ValueError):admission.select(self.b,self.request,self.issue)
        del self.tasks[identity(70)]
        second=identity(71);self.bind(second,self.author,self.task,'implementation','creating',attempt=2)
        with self.assertRaises(ValueError):admission.select(self.b,self.request,self.issue)
        with self.assertRaises(ValueError):admission.select(self.b,second,self.issue)
        self.assertEqual(first['task_id'],self.task)

    def test_historical_author_handoff_is_not_adopted(self):
        self.start();self.tasks[self.task]['status']='completed'
        with self.assertRaises(ValueError):self.arm()

    def test_authority_is_reauthenticated_and_cannot_approve_itself(self):
        self.arm();self.start()
        original=copy.deepcopy(self.tasks[self.approvals['cto']])
        self.tasks[self.approvals['cto']]['result']['output']='{}'
        with self.assertRaises(ValidationError):admission.select(self.b,self.request,self.issue)
        self.tasks[self.approvals['cto']]=original
        with self.db() as c:c.execute('INSERT INTO tool_events VALUES(?,?)',(self.approvals['sponsor'],1))
        with self.assertRaises(ValueError):admission.select(self.b,self.request,self.issue)
        with self.assertRaises(ValueError):admission.arm(self.b,self.p,self.q,dict(cto=self.approvals['cto'],sponsor=self.approvals['cto']))

    def test_sponsor_binds_actual_cto_proposal_not_just_the_same_scope(self):
        self.tasks[self.approvals['sponsor']]['handoff_note']=admission.note(self.p,'cto')
        with self.assertRaises(ValueError):self.arm()

    def test_qualification_limits_and_image_pins_are_not_advisory(self):
        for key in admission.FLAGS:
            q=copy.deepcopy(self.q);q['proof'][key]=False;p={**self.p,'qualification_sha256':admission.digest(q)}
            with self.subTest(key=key),self.assertRaises(ValueError):admission.validate_qualification(p,q)
        with self.assertRaises(ValueError):admission.validate_policy(self.b,{**self.p,'max_candidates':5})
        with patch.dict('os.environ',BROKER_AUTHOR_FEEDBACK_WORKER_IMAGE='sha256:'+'f'*64):
            with self.assertRaises(ValueError):self.arm()

    def test_close_requires_native_terminal_and_closed_lease_then_unblocks_unrelated_runs(self):
        self.arm();self.start();admission.select(self.b,self.request,self.issue);key=admission.digest(self.p)
        with self.assertRaises(ValueError):admission.close(self.b,key)
        with self.db() as c:c.execute('UPDATE leases SET status=? WHERE request_id=?',('closed',self.request))
        with self.assertRaises(ValueError):admission.close(self.b,key)
        self.tasks[self.task]['status']='completed'
        self.assertEqual(admission.close(self.b,key)['stage'],'closed')
        self.assertEqual(admission.close(self.b,key)['stage'],'closed')
        self.assertIsNone(admission.select(self.b,self.request,self.issue))
        self.assertEqual(self.arm()['stage'],'closed')

    def test_attach_issues_only_after_selection_and_real_rpc_checks(self):
        self.arm();self.start()
        with patch.object(admission.rpc,'issue',return_value='scoped') as issue,patch.object(admission.rpc,'attached_config',return_value={'capability':'scoped'}) as attach:
            self.assertEqual(admission.attach(self.b,self.request),{'capability':'scoped'})
            self.assertEqual(issue.call_args.args[2]['task_id'],self.task);attach.assert_called_once_with(self.b,self.request)

    def test_real_broker_constructor_selects_feedback_image_without_generic_policy_or_credentials(self):
        from broker import product_scope_worker,u3_controls_execution,surgical_recovery,driver_checkpoint_policy,template_author_executor
        with patch.dict(os.environ,BROKER_WORKER_IMAGE='sha256:'+'a'*64):
            spec=importlib.util.spec_from_file_location('feedback_broker_constructor',Path(__file__).resolve().parents[1]/'broker'/'server.py')
            server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
        self.arm();self.start()
        scope='workspace:implementation:'+self.task
        def docker(method,path,*args):
            if path.startswith('/images/'):return self.b.docker(method,path)
            if path.startswith('/volumes/'):
                if path=='/volumes/'+self.p['previous_volume']:return self.b.docker(method,path)
                return dict(Labels={'delivery-kit.owner':'owner','delivery-kit.scope':scope})
            raise AssertionError((method,path))
        with patch.object(server,'STATE',self.b.STATE),patch.object(server,'db',self.b.db),patch.object(server,'PREFIX',self.b.PREFIX),patch.object(server,'OWNER',self.b.OWNER),\
                patch.object(server,'native_scope',return_value=scope),patch.object(server,'native_mode',return_value='implementation'),\
                patch.object(server,'seed_workspace'),patch.object(server,'docker',side_effect=docker),\
                patch.object(product_scope_worker,'selection',return_value=None),patch.object(u3_controls_execution,'worker_config',return_value=None),\
                patch.object(surgical_recovery,'worker_config',return_value=None),patch.object(driver_checkpoint_policy,'worker_config',return_value=None),\
                patch.object(template_author_executor,'worker_config',return_value=None):
            result=server.config(self.request,'acp-session')
        self.assertEqual(result['Image'],self.p['worker_image'])
        self.assertTrue(result['HostConfig']['ReadonlyRootfs'])
        self.assertNotIn('capability',json.dumps(result));self.assertNotIn('docker.sock',json.dumps(result))
        self.assertFalse(any(e.startswith(('DELIVERY_ADDITIVE_TEST_JSON=','DELIVERY_SURGICAL_TEST_JSON=')) for e in result['Env']))

    def test_real_rpc_issuance_and_acp_environment_are_bound_to_same_claimed_execution(self):
        from broker import acp_transport
        self.arm();self.start();admission.select(self.b,self.request,self.issue)
        self.b.TOKEN='private-controller-fixture'
        with self.db() as c:
            c.execute('ALTER TABLE leases ADD COLUMN name');c.execute('ALTER TABLE leases ADD COLUMN deadline')
            c.execute('UPDATE leases SET status=?,name=?,deadline=? WHERE request_id=?',
                ('running',self.b.PREFIX+'-job-'+self.request,time.time()+300,self.request))
        original=self.b.docker
        self.b.docker=lambda method,path:dict(Image=self.p['worker_image']) if path.startswith('/containers/') else original(method,path)
        attached=admission.attach(self.b,self.request)
        self.assertEqual(attached['request_id'],self.request);self.assertEqual(attached['task_id'],self.task)
        env=acp_transport.worker_env('implementation',True,execution_id=self.request,author_feedback_config=attached)
        self.assertIn('DELIVERY_MODEL_EXECUTION_ID='+self.request,env)
        self.assertEqual(json.loads(next(v.split('=',1)[1] for v in env if v.startswith('DELIVERY_AUTHOR_FEEDBACK_JSON='))),attached)
        self.assertNotIn(self.b.TOKEN,json.dumps(env))
        with self.assertRaises(ValueError):acp_transport.worker_env('review',True,execution_id=self.request,author_feedback_config=attached)

    def test_failed_settled_execution_retires_automatically_but_unknown_container_does_not(self):
        self.arm();self.start();admission.select(self.b,self.request,self.issue)
        self.tasks[self.task]['status']='failed'
        with self.db() as c:c.execute('UPDATE leases SET status=? WHERE request_id=?',('failed',self.request))
        original=self.b.docker
        self.b.docker=lambda method,path:dict(State=dict(Running=True)) if path.startswith('/containers/') else original(method,path)
        admission.reconcile(self.b)
        with self.db() as c:
            self.assertEqual(json.loads(c.execute('SELECT state FROM author_feedback_admissions').fetchone()[0])['stage'],'claimed')
            observation=json.loads(c.execute('SELECT receipt FROM author_feedback_admission_observations').fetchone()[0])
            self.assertEqual(observation['owner'],self.cto);self.assertFalse(observation['delivery_approval'])
        self.b.docker=original;admission.reconcile(self.b)
        with self.db() as c:
            state=json.loads(c.execute('SELECT state FROM author_feedback_admissions').fetchone()[0])
            self.assertEqual(state['stage'],'closed');self.assertEqual(state['native_status'],'failed');self.assertFalse(state['delivery_approval'])
            self.assertEqual(json.loads(c.execute('SELECT receipt FROM author_feedback_admission_observations').fetchone()[0])['stage'],'settled_scope_closed')
