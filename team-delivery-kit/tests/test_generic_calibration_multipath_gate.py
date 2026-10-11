import copy
import json
from types import SimpleNamespace
import unittest

from broker import generic_calibration_gate as gate
from broker.generic_calibration_registration import context_from_inputs
from generic_calibration_input_probe import run
from generic_harness_calibration import digest
import test_generic_harness_calibration_v2 as samples
import test_generic_calibration_pipeline as pipeline_samples


class MultiPathGateTests(unittest.TestCase):
    def setUp(self):
        s=samples.MultiPathCalibrationTests();s.setUp();self.addCleanup(s.doCleanups)
        self.sample=s;self.p=s.policy
        self.context=dict(issue_id='issue',author_task='author-task',author='author',cto='cto',reviewer='lead',
            proposal_wakeup='proposal-wake',review_wakeup='review-wake',previous_methods=self.p['previous_methods'],
            execution_sha256=self.p['execution_sha256'],plan_sha256=self.p['plan_sha256'],source_task=self.p['source_task'],
            criteria=self.p['criteria'],control_files=list(s.control_files),candidate_volume='delivery-kit-port2-candidate',
            controls_volume='delivery-kit-port2-controls',policy_volume='delivery-kit-port2-policy')
        self.b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='owned',
            GENERIC_CALIBRATION_IMAGE='sha256:'+'a'*64,GENERIC_CALIBRATION_V2_IMAGE='sha256:'+'b'*64)

    def record(self,reads=None):
        def task(actor,wakeup,action):
            return dict(id=actor+'-task',agent_id=actor,issue_id='issue',status='completed',wakeup_id=wakeup,
                result=dict(output=json.dumps(dict(action=action,policy_sha256=digest(self.p),
                    controls_manifest_sha256=self.p['controls_manifest_sha256'],
                    execution_authorized=False,delivery_approval=False))))
        proof={path:dict(lines=4,total_lines=4) for path in gate.required_paths(self.p,self.context)}
        return gate.qualify(self.p,self.context,task('cto','proposal-wake','propose_calibration'),
            task('lead','review-wake','approve_calibration'),proof,proof if reads is None else reads)

    def test_independent_review_reads_every_product_and_control(self):
        paths=gate.required_paths(self.p,self.context)
        self.assertIn('/evidence/candidate/app/app.js',paths)
        self.assertIn('/evidence/candidate/app/index.html',paths)
        record=self.record();self.assertIs(record['execution_authorized'],False)
        reads={p:dict(lines=4,total_lines=4) for p in paths}
        del reads['/evidence/candidate/app/index.html']
        with self.assertRaises(ValueError):self.record(reads)
        self.context['reviewer']='author'
        with self.assertRaises(ValueError):self.record()

    def test_v2_requires_separately_configured_image_and_fixed_command(self):
        record=self.record();payload=gate.payload(self.b,record)
        self.assertEqual(payload['Image'],self.b.GENERIC_CALIBRATION_V2_IMAGE)
        self.assertEqual(payload['Cmd'][0],'/generic_harness_calibration_v2.py')
        self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
        self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))
        self.assertEqual(payload['Labels']['com.docker.compose.project'],'delivery-kit-port2-tests')
        for field,value in (('Cmd',['/bin/sh']),('Image',self.b.GENERIC_CALIBRATION_IMAGE),
                ('Env',['UNEXPECTED_ENV=1'])):
            changed=copy.deepcopy(payload);changed[field]=value
            with self.assertRaises(ValueError):gate.verify_payload(self.b,record,changed)
        del self.b.GENERIC_CALIBRATION_V2_IMAGE
        with self.assertRaises(ValueError):gate.payload(self.b,record)

    def test_stale_review_of_previous_policy_is_rejected(self):
        old=self.record()
        self.p['plan_sha256']='d'*64;self.context['plan_sha256']='d'*64
        self.assertNotEqual(old['policy_sha256'],digest(self.p))
        task=dict(id='lead-task',agent_id='lead',issue_id='issue',status='completed',wakeup_id='review-wake',
            result=dict(output=json.dumps(dict(action='approve_calibration',policy_sha256=old['policy_sha256'],
                controls_manifest_sha256=self.p['controls_manifest_sha256'],execution_authorized=False,delivery_approval=False))))
        reads={p:dict(lines=4,total_lines=4) for p in gate.required_paths(self.p,self.context)}
        with self.assertRaises(ValueError):gate.attest(self.p,self.context,task,'lead','review-wake','approve_calibration',reads)

    def test_input_registration_binds_v2_operation_and_both_product_hashes(self):
        previous=self.sample.candidate.parent/'previous';previous.mkdir();path='tests/test_ui.py'
        manifest,files=self.sample.snapshot(previous,{path:(self.sample.candidate/path).read_text()})
        value=dict(source_task=self.p['source_task'],plan_sha256=self.p['plan_sha256'],
            criteria={c:'approved' for c in self.p['criteria']},steps=[dict(editable_files=[path])],
            previous_new_test_delivery=dict(volume='delivery-kit-port2-previous',task_id='previous-task',
                manifest_sha256=manifest,test_sha256={path:files[path]['sha256']}))
        self.p['execution_sha256']=digest(value);self.context['execution_sha256']=digest(value)
        proof=run(self.sample.candidate,previous,self.sample.controls,self.p,digest(self.p),manifest)
        route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',test_first_files=[path])
        intake=dict(policy=self.p,context=self.context,previous=value['previous_new_test_delivery'])
        self.assertEqual(context_from_inputs(value,route,intake,proof),self.context)
        for mutate in (lambda p:p.update(operation='generic_calibration_inputs_v1'),
                lambda p:p['product_sha256'].pop('app/index.html')):
            bad=copy.deepcopy(proof);mutate(bad)
            with self.assertRaises(ValueError):context_from_inputs(value,route,intake,bad)

    def pipeline(self):
        from generic_harness_calibration_v2 import run as execute
        # Synthetic fixtures only; this exercises validation, not native approval.
        fixture=pipeline_samples.PipelineTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.record=self.record()
        fixture.receipt=execute(self.sample.candidate,self.sample.controls,self.p,digest(self.p))
        fixture.intake=dict(policy=self.p,context=self.context,proposal_task='cto-task',review_task='lead-task')
        fixture.initial.update(policy_sha256=digest(self.p),intake_sha256=digest(fixture.intake))
        fixture.con.execute('UPDATE generic_calibration_workflows SET state=?',
            (json.dumps(fixture.initial),))
        return fixture

    def test_pipeline_accepts_exact_v2_receipt_without_product_authority(self):
        fixture=self.pipeline()
        fixture.advance();fixture.advance(2);fixture.advance(3)
        state=fixture.state()
        self.assertEqual(state['stage'],'calibration_ready')
        self.assertEqual(state['calibration_receipt']['operation'],'generic_harness_calibration_v2')
        self.assertIs(state['execution_authorized'],False)
        self.assertIs(state['delivery_approval'],False)

    def test_pipeline_rejects_cross_version_receipt_and_stays_owned_hold(self):
        fixture=self.pipeline();fixture.receipt['operation']='generic_harness_calibration_v1'
        fixture.advance();fixture.advance(2);fixture.advance(3)
        state=fixture.state()
        self.assertEqual(state['stage'],'blocked')
        self.assertEqual(state['category'],'calibration_actual_job_rejected')
        self.assertEqual(state['owner'],'cto')
        events=list(fixture.events);fixture.advance(4)
        self.assertEqual(fixture.events,events)
