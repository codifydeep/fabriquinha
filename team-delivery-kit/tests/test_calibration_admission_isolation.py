"""Slow calibration evidence must not hold the native admission mutex."""
import contextlib
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from broker import generic_calibration_workflow as workflow
from broker import maintained_test_calibration as maintained
from broker import calibration_source
from broker.calibration_coordination import LOCK


class StopEvidence(Exception):
    pass


class AdmissionIsolationTests(unittest.TestCase):
    def test_enrollment_and_reconciliation_retain_shared_lane_serialization(self):
        self.assertIs(workflow.CALIBRATION_LOCK, LOCK)
        self.assertIs(maintained.CALIBRATION_LOCK, LOCK)
        acquired=[]
        def contender():
            available=LOCK.acquire(timeout=0.1)
            acquired.append(available)
            if available:LOCK.release()
        with LOCK:
            with LOCK:  # maintained reconciliation can enroll ordinary calibration
                thread=threading.Thread(target=contender)
                thread.start();thread.join(1)
        self.assertEqual(acquired,[False])

    def check_isolation(self, operation, install):
        admission = threading.RLock()
        entered, release, finished = (threading.Event() for _ in range(3))
        errors = []
        con = Mock()
        con.execute.return_value.fetchone.return_value = (
            '{}', json.dumps(dict(stage='maintenance_approved', review_phase='escalated')))

        @contextlib.contextmanager
        def db():
            yield con

        broker = SimpleNamespace(LOCK=admission, db=db)

        def slow(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError('test did not release evidence operation')
            raise StopEvidence()

        def run():
            try:
                operation(broker)
            except StopEvidence:
                pass
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        with install(slow):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(2), 'evidence operation never started')
                available = admission.acquire(timeout=0.15)
                if available:
                    admission.release()
                self.assertTrue(available, 'evidence reconciliation blocks native admission')
            finally:
                release.set()
                worker.join(3)
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])

    def test_workflow_tick_does_not_hold_admission_lock(self):
        self.check_isolation(workflow.tick,
            lambda slow: patch.object(workflow, 'initialize', side_effect=slow))

    def test_source_enrollment_does_not_hold_admission_lock(self):
        self.check_isolation(lambda b: workflow.request(b, 'issue', 'author',
            engine='unittest_path_fixture_v1'),
            lambda slow: patch.object(calibration_source, 'qualified', side_effect=slow))

    def test_maintained_snapshot_validation_does_not_hold_admission_lock(self):
        self.check_isolation(lambda b: maintained.handle(b, 'source'),
            lambda slow: patch.object(maintained, 'configuration', side_effect=slow))
