import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from docker_grouping import grouped_create
from generic_harness_calibration import digest
from broker import literal_maintenance_effects as effects
from broker.test_first_job import digest as job_digest


class CaptureEffectsTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE validation_jobs(job_key TEXT,identity TEXT,state TEXT)')
        self.b=SimpleNamespace(db=lambda:self.con,PREFIX='delivery-kit-port2',OWNER='owner')
        self.fx=object.__new__(effects.Effects);self.fx.b=self.b
        self.cfg=dict(test_path='tests/test.py',counterexample={'facts':{'assertion_bindings':
            dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11')}})
        self.s=dict(diagnosis=dict(task_id='11111111-1111-4111-8111-111111111111',value={'action':'request_test_revision'}),
            snapshot={'volume':'unrelated-current'},history=[{},dict(snapshot={'volume':'second-rejected'},inspection=dict(
                candidate_manifest_sha256='a'*64,structure=dict(candidate_test_sha256='b'*64,candidate_literal_sha256='c'*64)))])
        environment=patch.dict(effects.os.environ,{'BROKER_LITERAL_CAPTURE_EXPERIMENT_IMAGE':'sha256:'+'d'*64})
        environment.start();self.addCleanup(environment.stop)

    def journal(self):
        task=self.s['diagnosis']['task_id'];payload=grouped_create('POST','/containers/create?name=validation',
            effects.capture_payload(self.cfg,self.s),self.b.PREFIX)
        key=job_digest(dict(task=task,kind='structure',payload=payload))
        expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':'owner',
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind='structure',name=self.b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        reports={v:{d:dict(initial_requests=1,poll_requests=3 if v=='before_capture' else 2,
            stale_guard_text='Newest matching: #11' if d=='guarded' else 'Newest matching: #4')
            for d in ('guarded','unguarded')} for v in ('original','before_capture','after_capture')}
        value=dict(operation='literal_poll_capture_counterfactual_v1',test_path='tests/test.py',
            candidate_manifest_sha256='a'*64,test_sha256='b'*64,diagnosis_sha256=digest(self.s['diagnosis']),
            experiment_sha256=hashlib.sha256(Path(effects.capture.__file__).read_bytes()).hexdigest(),
            assertion_bindings=self.cfg['counterexample']['facts']['assertion_bindings'],snapshot_unchanged=True,
            counterfactual_templates_only=True,model_calls=0,template_sha256={'original':'c'*64},
            reports=reports,hypothesis_supported=True,**{k:False for k in effects.protocol.FALSE_FLAGS})
        output=json.dumps(value,sort_keys=True)
        result=dict(container_id='completed-helper',approval=False,exit_code=0,output=output,
            output_sha256=hashlib.sha256(output.encode()).hexdigest(),validation_job_key=key,
            validation_contract_sha256=job_digest(identity))
        self.con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',(key,json.dumps(identity),
            json.dumps(dict(stage='complete',container_id='completed-helper',result=result))))
        return {**value,'validation_job':result}

    def test_fixed_sandbox_reads_rejected_snapshot_and_accepts_no_model_command(self):
        payload=effects.capture_payload(self.cfg,self.s);host=payload['HostConfig']
        self.assertEqual(host['NetworkMode'],'none');self.assertTrue(host['ReadonlyRootfs'])
        self.assertEqual(host['Mounts'],[dict(Type='volume',Source='second-rejected',Target='/candidate',ReadOnly=True)])
        self.assertEqual(payload['Cmd'][0],'/literal_poll_capture_experiment.py')
        self.assertEqual(payload['Cmd'][-1],digest(self.s['diagnosis']))
        self.assertEqual(payload['User'],'10000:10000');self.assertNotIn('Binds',host)

    def test_captured_job_can_be_verified_after_helper_retirement_without_running_it_again(self):
        value=self.journal();self.fx.validate_experiment(self.cfg,self.s,value)
        self.assertFalse(value['author_retry_authorized']);self.assertFalse(value['delivery_approval'])
        self.fx.validate_experiment(self.cfg,self.s,value)
        self.assertEqual(self.con.execute('SELECT count(*) FROM validation_jobs').fetchone()[0],1)

    def test_output_tampering_stale_diagnosis_or_pending_job_is_rejected(self):
        value=self.journal();value['reports']['before_capture']['guarded']['poll_requests']=4
        with self.assertRaises(ValueError):self.fx.validate_experiment(self.cfg,self.s,value)
        value['reports']['before_capture']['guarded']['poll_requests']=3
        self.s['diagnosis']['value']['reason']='a different diagnosis'
        with self.assertRaises(ValueError):self.fx.validate_experiment(self.cfg,self.s,value)
        self.s['diagnosis']['value'].pop('reason')
        row=self.con.execute('SELECT state FROM validation_jobs').fetchone();state=json.loads(row[0]);state['stage']='running'
        self.con.execute('UPDATE validation_jobs SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):self.fx.validate_experiment(self.cfg,self.s,value)
