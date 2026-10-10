import copy
import json
import unittest

from broker import generic_calibration_registration as registration
import test_generic_calibration_gate as samples
import test_generic_calibration_registration as inputs
from generic_harness_calibration import digest


class InputJobTests(unittest.TestCase):
    def job(self, uncertain=None):
        sample=samples.GenericCalibrationGateTests();sample.setUp()
        self.addCleanup(sample.doCleanups)
        b,con,record,calls,container=sample.job(uncertain)
        fixture=inputs.RegistrationInputTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        intake=fixture.intake
        original=b.docker
        def docker(method,path,body=None):
            if path.startswith('/volumes/'):
                role=path.rsplit('-',1)[-1]
                return dict(Labels={'delivery-kit.owner':b.OWNER,
                    'delivery-kit.test-first-task':'previous-task' if role=='previous' else 'author-task',
                    'delivery-kit.calibration-policy':digest(intake['policy']),
                    'delivery-kit.calibration-role':role})
            return original(method,path,body)
        b.docker=docker
        intake['probe_job_key']='issue:author-task:inputs'
        registration.initialize(con)
        con.execute('INSERT INTO generic_calibration_intakes VALUES(?,?,?)',
            ('issue','author-task',json.dumps(intake)))
        raw=json.dumps(fixture.proof)
        b.docker_stdout=lambda *a,**k:raw
        return b,con,intake,fixture.value,fixture.route,calls,container

    def test_lost_create_or_start_ack_is_observed_without_duplicate_effects(self):
        for phase in ('create','start'):
            with self.subTest(phase=phase):
                b,con,intake,value,route,calls,container=self.job(phase)
                with self.assertRaises(TimeoutError):
                    registration.run_inputs(b,con,intake,value,route,now=1)
                result=registration.run_inputs(b,con,intake,value,route,now=2)
                self.assertFalse(result['approval'])
                self.assertFalse(json.loads(result['output'])['tests_executed'])
                self.assertEqual(sum(m=='POST' and '/create' in p for m,p in calls),1)
                self.assertEqual(sum(m=='POST' and '/start' in p for m,p in calls),1)

    def test_missing_handle_is_not_recreated(self):
        b,con,intake,value,route,calls,container=self.job('create')
        with self.assertRaises(TimeoutError):registration.run_inputs(b,con,intake,value,route,now=1)
        container.clear()
        with self.assertRaises(TimeoutError):registration.run_inputs(b,con,intake,value,route,now=2)
        self.assertEqual(sum(m=='POST' for m,p in calls),1)

    def test_tampered_receipt_blocks_without_identical_retry(self):
        b,con,intake,value,route,calls,container=self.job()
        b.docker_stdout=lambda *a,**k:'{}'
        with self.assertRaises(ValueError):registration.run_inputs(b,con,intake,value,route,now=1)
        before=len(calls)
        with self.assertRaises(ValueError):registration.run_inputs(b,con,intake,value,route,now=2)
        self.assertEqual(len(calls),before)

    def test_unpersisted_intake_and_changed_binding_cannot_execute(self):
        b,con,intake,value,route,calls,container=self.job()
        bad=copy.deepcopy(intake);bad['context']['author_task']='replacement'
        with self.assertRaises(ValueError):registration.run_inputs(b,con,bad,value,route,now=1)
        self.assertFalse(calls)

    def test_completed_proof_is_reused_but_changed_execution_is_rejected(self):
        b,con,intake,value,route,calls,container=self.job()
        result=registration.run_inputs(b,con,intake,value,route,now=1)
        before=len(calls)
        self.assertEqual(registration.run_inputs(b,con,intake,value,route,now=2),result)
        self.assertEqual(len(calls),before)
        changed=copy.deepcopy(value);changed['criteria']['A02']='new unapproved scope'
        with self.assertRaises(ValueError):registration.run_inputs(b,con,intake,changed,route,now=3)
        self.assertEqual(len(calls),before)

    def test_deadline_preserves_unknown_effect_and_does_not_recreate(self):
        b,con,intake,value,route,calls,container=self.job('create')
        with self.assertRaises(TimeoutError):registration.run_inputs(b,con,intake,value,route,now=1)
        before=len(calls)
        with self.assertRaises(ValueError):registration.run_inputs(b,con,intake,value,route,now=602)
        state=json.loads(con.execute('SELECT state FROM generic_calibration_input_jobs').fetchone()[0])
        self.assertEqual(state['stage'],'blocked')
        self.assertEqual(state['category'],'input_observation_deadline')
        self.assertTrue(container)
        self.assertEqual(len(calls),before)
