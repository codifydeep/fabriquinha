import unittest
from unittest.mock import Mock
import host_awake_guard as guard


class AwakeGuardTests(unittest.TestCase):
    def fixture(self):
        self.now=0
        def sleep(seconds):self.now+=seconds
        child=Mock();child.poll.return_value=None
        return dict(popen=Mock(return_value=child),active=Mock(return_value=0),clock=lambda:self.now,sleep=sleep,report=Mock())

    def test_idle_assertion_is_project_scoped_bounded_and_removed_on_idle(self):
        f=self.fixture();self.assertEqual(guard.run('delivery-kit-port2',60,20,**f),'idle')
        f['popen'].assert_called_once();self.assertEqual(f['popen'].call_args.args[0],['/usr/bin/caffeinate','-i','-t','60'])
        f['active'].assert_called_with('delivery-kit-port2');f['popen'].return_value.terminate.assert_called_once()

    def test_active_workers_cannot_extend_guard_past_duration(self):
        f=self.fixture();f['active'].return_value=1
        self.assertEqual(guard.run('delivery-kit-port2',60,20,**f),'duration_limit')
        self.assertEqual(self.now,60);f['popen'].return_value.terminate.assert_called_once()

    def test_inspection_error_releases_assertion_and_never_launches_workers(self):
        f=self.fixture();f['active'].side_effect=OSError()
        with self.assertRaises(OSError):guard.run('delivery-kit-port2',60,20,**f)
        f['popen'].return_value.terminate.assert_called_once()

    def test_unbounded_or_unrelated_scope_is_rejected_before_power_assertion(self):
        for project,duration,grace in [('toso-prod',60,20),('delivery-kit-port2',7200,20),('delivery-kit-port2',60,100)]:
            f=self.fixture()
            with self.assertRaises(ValueError):guard.run(project,duration,grace,**f)
            f['popen'].assert_not_called()

    def test_system_sleep_prevention_is_explicit_ac_only_and_bounded(self):
        f=self.fixture()
        self.assertEqual(guard.run('delivery-kit-port2',60,20,prevent_system_sleep_on_ac=True,**f),'idle')
        self.assertEqual(f['popen'].call_args.args[0],['/usr/bin/caffeinate','-i','-s','-t','60'])
        f['popen'].return_value.terminate.assert_called_once()

    def test_non_boolean_system_sleep_option_cannot_enable_assertion(self):
        for value in ('true',1,None):
            f=self.fixture()
            with self.assertRaises(ValueError):
                guard.run('delivery-kit-port2',60,20,prevent_system_sleep_on_ac=value,**f)
            f['popen'].assert_not_called()
