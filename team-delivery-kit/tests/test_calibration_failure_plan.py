import copy
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from broker import calibration_failure_plan as plan,calibration_rework as lane,handoffs,harness_qualification as jobs
from service_mode_harness_qualification import TEST,CASES,fixture


class CalibrationFailurePlanTests(unittest.TestCase):
    def proof(self):
        clean=dict(tests=15,failures=0,errors=0,skipped=0,unexpected_successes=0,expected_failures=0)
        negative={case:{**clean,'tests':1,'failures':1} for case in CASES}
        variant=dict(operation='service_mode_harness_calibration_v1',status='passed',
            manifest_sha256='b'*64,test_sha256='d'*64,positive=clean,negative_controls=negative,
            compile=dict(manifest_sha256='b'*64,test_sha256='d'*64,
                         **{k:dict(exit_code=0) for k in ('control','harness','product')}),
            control_fixture_sha256={case:hashlib.sha256(fixture(case).encode()).hexdigest() for case in ['positive',*CASES]},
            product_green=False,red_approved=False,delivery_approval=False)
        return dict(operation='fixed_observation_hypothesis_v1',status='supported',
            hypothesis='fresh_terminal_observation_after_async_settlement',original_manifest_sha256='a'*64,
            original_test_sha256='c'*64,variant_manifest_sha256='b'*64,variant_test_sha256='d'*64,
            original=dict(status='rejected',phase='positive_reference',facts=dict(manifest_sha256='a'*64,test_sha256='c'*64,
                positive={**clean,'failures':2,'failed_methods':['test_exact_demo_object_yields_demo_environment','test_indicator_text_constants_are_exact']})),
            variant=variant,inputs_unchanged=True,original_test_bodies_unchanged=True,diagnostic_copy_only=True,
            valid_red_green_receipt=False,author_retry_authorized=False,delivery_approval=False)

    def test_only_actual_complete_diagnostic_copy_can_sponsor_plan(self):
        proof=self.proof();identity=dict(manifest_sha256='a'*64)
        plan.validate_experiment(proof,identity)
        for change in [dict(delivery_approval=True),dict(author_retry_authorized=True),dict(status='refuted'),
                       dict(original_manifest_sha256='x'*64),dict(variant_manifest_sha256='a'*64)]:
            with self.assertRaises(ValueError):plan.validate_experiment({**proof,**change},identity)
        changed=copy.deepcopy(proof);changed['variant']['negative_controls'].pop('duplicate_request')
        with self.assertRaises(ValueError):plan.validate_experiment(changed,identity)

    def test_independent_plan_lane_never_dispatches_an_author(self):
        config=dict(issue_id='issue',source_task='failed',author='author',cto='cto',peer='peer',minimum_calls=8,
            manifest_sha256='a'*64,diagnosis_only=True,criteria={'A01':'unchanged'},
            paths=['/evidence/candidate/tests/test_new.py'],diagnostic={'phase':'positive_reference'},
            experiment_summary={'diagnostic_copy_only':True,'delivery_approval':False})
        saved=[];calls=[]
        def wake(*args,**kwargs):calls.append(args);return {'id':'wake-'+args[1]}
        fx=SimpleNamespace(remaining_calls=lambda:100,ensure_wakeup=wake,
            decision=lambda task:dict(action='request_test_revision',reason='Fresh observation after settling.',optional_files=[]),
            read_evidence=lambda task:{config['paths'][0]:dict(lines=1,total_lines=1)})
        state=dict(stage='cto_pending',author_retry_authorized=False)
        runs=[]
        state=lane.advance(config,state,runs,fx,saved.append)
        runs.append(dict(id='cto-task',agent_id='cto',wakeup_id='wake-cto',status='completed'))
        state=lane.advance(config,state,runs,fx,saved.append)
        state=lane.advance(config,state,runs,fx,saved.append)
        runs.append(dict(id='peer-task',agent_id='peer',wakeup_id='wake-peer',status='completed'))
        state=lane.advance(config,state,runs,fx,saved.append)
        state=lane.advance(config,state,runs,fx,saved.append)
        self.assertEqual(state['stage'],'plan_qualified');self.assertEqual([a[1] for a in calls],['cto','peer'])
        self.assertFalse(state['author_retry_authorized']);self.assertFalse(state['delivery_approval'])
        self.assertIn('POST-FAILURE PLAN ONLY',lane.instruction(config,dict(stage='cto_pending')))
        self.assertEqual(lane.advance(config,state,runs,fx,saved.append),state)
        from decision_schema import apply as schema
        from typed_decision_contract import apply as adapter,NAME
        note=lane.instruction(config,dict(stage='cto_pending'))
        self.assertNotIn('A request sponsors one changed-evidence gate rework',note)
        body=dict(messages=[dict(role='user',content=note)],tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
        body['messages'] += [dict(role='assistant',tool_calls=[dict(id='read',function=dict(name='read_file',
            arguments=json.dumps(dict(path=config['paths'][0],offset=1,limit=128))))]),
            dict(role='tool',tool_call_id='read',content=json.dumps(dict(content='1|pass',total_lines=1)))]
        result=adapter(schema(body))
        self.assertEqual(result['tool_choice']['function']['name'],NAME)
        self.assertEqual(set(result['tools'][0]['function']['parameters']['properties']),{'action','reason','optional_files'})

    def test_sql_intake_observes_real_job_identity_once_and_preserves_failed_coordination(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con);lane.initialize(con)
        con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT)')
        con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
        con.execute('CREATE TABLE observation_hypothesis_experiments(source_task TEXT,identity TEXT,state TEXT)')
        con.execute("INSERT INTO leases VALUES('request','closed')")
        con.execute("INSERT INTO native_bindings VALUES('request','failed','issue','author')")
        route=dict(issue_id='issue',author='author',cto='cto',techlead='peer',contract_sha256='z'*64,enabled=True)
        previous=dict(issue_id='issue',source_task='old',author='author',cto='cto',peer='peer',contract_sha256='z'*64,
            minimum_calls=8,paths=['/evidence/candidate/tests/test_new.py'],criteria={'A01':'unchanged'})
        held=dict(stage='blocked',category='calibration_author_failed',author_task='failed',author_wakeup='author-wake')
        con.execute('INSERT INTO calibration_reworks VALUES(?,?,?,?)',('issue','old',json.dumps(previous),json.dumps(held)))
        handoffs.save(con,'failed','issue','test_first_blocked','cto',dict(error='author failed'),0)
        proof=self.proof();raw=json.dumps(proof)
        @contextmanager
        def db():yield con;con.commit()
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),OWNER='owned',docker_stdout=lambda *a,**kw:raw)
        def docker(method,path,body=None):
            if path.startswith('/images/'):return dict(Id='sha256:'+'e'*64,Config=dict(Env=['PATH=/bin']))
            if path.startswith('/volumes/'):return dict(Labels={'delivery-kit.owner':'owned','delivery-kit.source-task':'failed','delivery-kit.diagnostic-only':'true'})
            return info
        b.docker=docker
        image=SimpleNamespace(IMAGE='sha256:'+'e'*64,OWNER='owned',docker=docker)
        payload=jobs.payload(image,'failed','snapshot','a'*64)
        payload['Cmd']=['/service_mode_observation_hypothesis.py','/delivery','a'*64]
        payload['Labels']['delivery-kit.purpose']='observation-hypothesis'
        info=dict(Id='job',Config={k:v for k,v in payload.items() if k!='HostConfig'},HostConfig=payload['HostConfig'],
                  State=dict(Status='exited',Running=False,ExitCode=0))
        identity=dict(source_task='failed',issue_id='issue',volume='snapshot',manifest_sha256='a'*64,payload=payload)
        experiment=dict(stage='complete',container_id='job',receipt_sha256=hashlib.sha256(raw.encode()).hexdigest(),proof=proof)
        con.execute('INSERT INTO observation_hypothesis_experiments VALUES(?,?,?)',('failed',json.dumps(identity),json.dumps(experiment)))
        source=dict(id='failed',agent_id='author',status='failed',wakeup_id='author-wake');calls=[]
        fx=SimpleNamespace(remaining_calls=lambda:100,ensure_wakeup=lambda *a,**kw:calls.append(a) or {'id':'cto-wake'})
        self.assertTrue(plan.handle(b,route,[source],source,handoffs.load(con,'failed'),fx))
        self.assertEqual(len(calls),1)
        self.assertEqual(json.loads(con.execute('SELECT state FROM calibration_reworks').fetchone()[0]),held)
        prior=handoffs.load(con,'failed');self.assertEqual(prior['stage'],'calibration_failure_plan')
        self.assertTrue(plan.handle(b,route,[source,dict(id='cto-task',agent_id='cto',wakeup_id='cto-wake',status='running')],source,prior,fx))
        self.assertEqual(len(calls),1)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM calibration_failure_plans').fetchone()[0],1)
