import copy
import unittest

from broker.generic_calibration_registration import context_from_inputs,copy_matches
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from generic_calibration_input_probe import run
from generic_harness_calibration import digest
import test_generic_calibration_gate as samples


class RegistrationInputTests(unittest.TestCase):
    def setUp(self):
        sample=samples.GenericCalibrationGateTests();sample.setUp();self.addCleanup(sample.doCleanups)
        self.policy=sample.policy;self.context=sample.context
        fixture=sample.fixture;prior=fixture.candidate.parent/'previous';prior.mkdir()
        path='tests/test_contract.py'
        manifest,files=fixture.snapshot(prior,{path:(fixture.candidate/path).read_text()})
        self.proof=run(fixture.candidate,prior,fixture.controls,self.policy,digest(self.policy),manifest)
        self.value=dict(source_task=self.policy['source_task'],plan_sha256=self.policy['plan_sha256'],
            criteria={'A01':'unchanged criterion'},steps=[dict(editable_files=[path])],
            previous_new_test_delivery=dict(volume='delivery-kit-port2-previous',task_id='previous-task',
                manifest_sha256=manifest,test_sha256={path:files[path]['sha256']}))
        self.policy['execution_sha256']=digest(self.value)
        self.proof['policy_sha256']=digest(self.policy)
        self.context['execution_sha256']=digest(self.value)
        self.route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',test_first_files=[path])
        self.intake=dict(policy=self.policy,context=self.context,previous=self.value['previous_new_test_delivery'])

    def test_input_context_comes_from_exact_original_delivery_and_execution(self):
        self.assertEqual(context_from_inputs(self.value,self.route,self.intake,self.proof),self.context)

    def test_forged_history_hashes_actor_or_execution_are_rejected(self):
        for mutate in (lambda i:i['context'].update(cto='author'),
                       lambda i:i['previous'].update(manifest_sha256='0'*64),
                       lambda i:i['policy'].update(plan_sha256='0'*64),
                       lambda i:i['policy'].update(execution_sha256='0'*64)):
            bad=copy.deepcopy(self.intake);mutate(bad)
            with self.assertRaises(ValueError):context_from_inputs(self.value,self.route,bad,self.proof)

    def test_candidate_volume_is_bound_to_the_completed_real_copy_job(self):
        raw=json.dumps(dict(manifest_sha256=self.policy['candidate_manifest_sha256'],
            test_sha256=self.policy['test_sha256']))
        state=dict(stage='complete',result=dict(exit_code=0,approval=False,output=raw,
            output_sha256=hashlib.sha256(raw.encode()).hexdigest()))
        identity=dict(payload=dict(Labels={'delivery-kit.test-first-task':self.context['author_task']},
            HostConfig=dict(Mounts=[dict(Target='/snapshot',Source=self.context['candidate_volume'])])))
        copy_matches(self.intake,identity,state)
        for mutate in (lambda i:i['payload']['HostConfig']['Mounts'][0].update(Source='replacement'),
                       lambda i:i['payload']['Labels'].update({'delivery-kit.test-first-task':'another-task'})):
            bad=copy.deepcopy(identity);mutate(bad)
            with self.assertRaises(ValueError):copy_matches(self.intake,bad,state)
        bad=copy.deepcopy(state);bad['result']['output_sha256']='0'*64
        with self.assertRaises(ValueError):copy_matches(self.intake,identity,bad)

    def test_probe_cannot_claim_execution_or_drop_original_methods(self):
        for mutate in (lambda p:p.update(tests_executed=True),
                       lambda p:p.update(previous_methods={}),
                       lambda p:p.update(previous_test_sha256={}),
                       lambda p:p.update(candidate_manifest_sha256='0'*64),
                       lambda p:p.update(delivery_approval=True)):
            bad=copy.deepcopy(self.proof);mutate(bad)
            with self.assertRaises(ValueError):context_from_inputs(self.value,self.route,self.intake,bad)

    def test_live_collector_fetches_bound_tasks_and_rejects_nonclosed_review_lease(self):
        from broker import generic_calibration_registration as registration
        from broker import remediation_runtime_guard as guard,remediation_admission as admission,technical_remediation_plan as plans
        self.value['amendment']={'kind':'inherited_frozen_suite'}
        self.policy['execution_sha256']=digest(self.value)
        self.context['execution_sha256']=digest(self.value);self.proof['policy_sha256']=digest(self.policy)
        self.intake.update(probe_job_key='input-job',proposal_task='cto-task',review_task='lead-task')
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        registration.initialize(con)
        con.executescript('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);'
            'CREATE TABLE test_first_jobs(job_key TEXT,identity TEXT,state TEXT);'
            'CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT);'
            'CREATE TABLE leases(request_id TEXT,status TEXT);')
        @contextmanager
        def db():
            yield con
            con.commit()
        image='sha256:'+'c'*64
        def docker(method,path,body=None):
            self.assertEqual(method,'GET')
            if path.startswith('/images/'):return dict(Id=image,Config=dict(Env=['PATH=/usr/bin']))
            role=path.rsplit('-',1)[-1]
            return dict(Labels={'delivery-kit.owner':'owned','delivery-kit.test-first-task':
                'previous-task' if role=='previous' else self.context['author_task'],
                'delivery-kit.calibration-policy':digest(self.policy),'delivery-kit.calibration-role':role})
        b=SimpleNamespace(LOCK=threading.RLock(),db=db,docker=docker,PREFIX='delivery-kit-port2',
            OWNER='owned',GENERIC_CALIBRATION_IMAGE=image)
        expected=registration.input_payload(b,self.intake);expected['Env']=['PATH=/usr/bin','PYTHONDONTWRITEBYTECODE=1']
        raw=json.dumps(self.proof);result=dict(exit_code=0,approval=False,output=raw,
            output_sha256=hashlib.sha256(raw.encode()).hexdigest())
        con.execute('INSERT INTO generic_calibration_input_jobs VALUES(?,?,?)',
            ('input-job',json.dumps({'payload':expected}),json.dumps({'stage':'complete','result':result})))
        con.execute('INSERT INTO generic_calibration_intakes VALUES(?,?,?)',
            ('issue','author-task',json.dumps(self.intake)))
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(self.route)))
        prepared=json.dumps(dict(manifest_sha256=self.policy['candidate_manifest_sha256'],test_sha256=self.policy['test_sha256']))
        copy=dict(payload=dict(Labels={'delivery-kit.test-first-task':'author-task'},
            HostConfig=dict(Mounts=[dict(Target='/snapshot',Source=self.context['candidate_volume'])])))
        state=dict(stage='complete',result=dict(exit_code=0,approval=False,output=prepared,
            output_sha256=hashlib.sha256(prepared.encode()).hexdigest()))
        con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',('author-task:copy',json.dumps(copy),json.dumps(state)))
        for actor in ('cto','lead','author'):
            mode='implementation' if actor=='author' else 'planning'
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(actor,actor+'-task',actor,
                'workspace:'+actor+':'+mode+':'+actor+'-task','issue'))
            con.execute('INSERT INTO leases VALUES(?,?)',(actor,'closed'))
        def task(tid,actor):
            return dict(id=tid,agent_id=actor,issue_id='issue',status='completed',
                wakeup_id=self.context['proposal_wakeup' if actor=='cto' else 'review_wakeup'],
                result=dict(output=json.dumps(dict(action='propose_calibration' if actor=='cto' else 'approve_calibration',
                    policy_sha256=digest(self.policy),controls_manifest_sha256=self.policy['controls_manifest_sha256'],
                    execution_authorized=False,delivery_approval=False))))
        reads={path:dict(lines=4,total_lines=4) for path in registration.gate.required_paths(self.policy,self.context)}
        fx=SimpleNamespace(settings={'agents':{'cto':'planning','lead':'planning','author':'implementation'}},task=task,reads=lambda t:reads)
        with patch.object(guard,'qualified',return_value=self.value),\
                patch.object(admission,'Effects',return_value=SimpleNamespace(plan=lambda s:(
                    dict(cto='cto',reviewer='lead',original_author='author'),dict(plan_sha256=self.value['plan_sha256'])))),\
                patch.object(plans,'Effects',return_value=fx):
            record=registration.register(b,'issue','author-task')
            self.assertFalse(record['execution_authorized'])
            con.execute('UPDATE leases SET status=? WHERE request_id=?',('running','lead'))
            with self.assertRaises(ValueError):registration.register(b,'issue','author-task')
