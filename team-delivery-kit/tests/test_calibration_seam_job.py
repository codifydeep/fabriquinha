import copy
import json
from types import SimpleNamespace
import unittest
from broker import generic_calibration_seam_job as job
import test_calibration_capability_recovery as samples
from docker_grouping import grouped_create


class SeamJobTests(unittest.TestCase):
    def setUp(self):
        sample=samples.CapabilityRecoveryTests();sample.setUp();self.addCleanup(sample.doCleanups)
        self.con=sample.con;self.c={**sample.c,'candidate_volume':'delivery-kit-port2-candidate'}
        self.proof=sample.proof;self.calls=[];self.container={};self.uncertain=None
        self.b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='owned',GENERIC_CALIBRATION_SEAM_IMAGE='sha256:'+'a'*64)
        def docker(method,path,body=None):
            if path.startswith('/images/'):return dict(Id=self.b.GENERIC_CALIBRATION_SEAM_IMAGE,Config=dict(Env=['PATH=/usr/bin']))
            if path.startswith('/volumes/'):return dict(Labels={'delivery-kit.owner':'owned','delivery-kit.test-first-task':self.c['author_task']})
            self.calls.append((method,path))
            if method=='GET':return copy.deepcopy(self.container) if self.container else None
            if path.startswith('/containers/create'):
                self.container.update(Id='container',Image=body['Image'],Config={k:copy.deepcopy(v) for k,v in body.items() if k!='HostConfig'},
                    HostConfig=copy.deepcopy(body['HostConfig']),State=dict(Status='created',ExitCode=0),
                    Mounts=[dict(Type='volume',Name=m['Source'],Destination=m['Target'],RW=False) for m in body['HostConfig']['Mounts']])
                if self.uncertain=='create':raise TimeoutError('unknown create acknowledgment')
            else:
                self.container['State']=dict(Status='exited',ExitCode=0)
                if self.uncertain=='start':raise TimeoutError('unknown start acknowledgment')
        self.b.docker=docker;self.b.docker_stdout=lambda *a,**k:json.dumps(self.proof)

    def test_fixed_readonly_probe_records_complete_evidence_and_never_runs_twice(self):
        result=job.run(self.b,self.con,self.c,now=1)
        self.assertIs(result['approval'],False)
        payload=job.payload(self.b,self.c)
        self.assertEqual(payload['Cmd'][0],'/generic_calibration_seam_probe.py')
        self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
        self.assertEqual(payload['Labels']['com.docker.compose.project'],'delivery-kit-port2-tests')
        self.assertEqual(job.run(self.b,self.con,self.c,now=2),result)
        self.assertEqual(sum(m=='POST' for m,p in self.calls),2)

    def test_lost_ack_observes_same_handle_without_repeated_create_or_start(self):
        for phase in ('create','start'):
            with self.subTest(phase=phase):
                fixture=SeamJobTests();fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.uncertain=phase
                with self.assertRaises(TimeoutError):job.run(fixture.b,fixture.con,fixture.c,now=1)
                fixture.uncertain=None;job.run(fixture.b,fixture.con,fixture.c,now=2)
                self.assertEqual(sum(m=='POST' for m,p in fixture.calls),2)

    def test_invalid_proof_stays_blocked_without_identical_retry(self):
        self.proof['execution_authorized']=True
        with self.assertRaises(ValueError):job.run(self.b,self.con,self.c,now=1)
        before=list(self.calls)
        with self.assertRaises(ValueError):job.run(self.b,self.con,self.c,now=2)
        self.assertEqual(self.calls,before)

    def test_controller_grouping_adapter_keeps_exact_recorded_create_observable(self):
        original=self.b.docker
        def grouped(method,path,body=None):
            return original(method,path,grouped_create(method,path,body,self.b.PREFIX) if body is not None else None)
        self.b.docker=grouped
        result=job.run(self.b,self.con,self.c,now=1)
        self.assertFalse(result['approval'])
        self.assertEqual(sum(m=='POST' for m,p in self.calls),2)

    def test_reference_control_job_is_fixed_isolated_and_not_a_calibration_registration(self):
        import test_calibration_control_experiment_probe as examples
        from generic_harness_calibration import digest
        import calibration_control_experiment_probe as probe
        fixture=examples.ControlExperimentProbeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.c.update(prepared=fixture.c['prepared'],test_files=fixture.c['test_files'])
        self.b.GENERIC_CALIBRATION_CONTROLS_IMAGE=self.b.GENERIC_CALIBRATION_SEAM_IMAGE
        self.proof=probe.run(fixture.f.candidate,fixture.bundle,digest(fixture.bundle))
        result=job.run(self.b,self.con,self.c,kind='controls',bundle=fixture.bundle,now=1)
        payload=job.payload(self.b,self.c,'controls',fixture.bundle)
        self.assertEqual(payload['Cmd'],['/calibration_control_experiment_probe.py','/candidate',digest(fixture.bundle)])
        self.assertEqual(payload['HostConfig']['NetworkMode'],'none');self.assertEqual(payload['HostConfig']['Memory'],536870912)
        self.assertEqual(len(payload['HostConfig']['Mounts']),1);self.assertTrue(payload['HostConfig']['Mounts'][0]['ReadOnly'])
        self.assertFalse(result['approval']);self.assertEqual(sum(m=='POST' for m,p in self.calls),2)
        self.assertEqual(job.run(self.b,self.con,self.c,kind='controls',bundle=fixture.bundle,now=2),result)
        self.assertEqual(sum(m=='POST' for m,p in self.calls),2)
