"""Qualification lifecycle only; mocked Docker is not isolation evidence."""
import unittest
from unittest.mock import patch
import qualify_quality_red_observer as qualification


class RedQualificationTests(unittest.TestCase):
    def test_fixed_invocation_has_group_isolation_and_no_host_mount_or_credentials(self):
        command=qualification.execution_args('delivery-kit-port2','delivery-kit-port2-red-probe-example','sha256:'+'a'*64)
        for value in ('--rm','--read-only','com.docker.compose.project=delivery-kit-port2-tests','--network','none','10000:10000'):
            self.assertIn(value,command)
        for value in ('--volume','-v','--mount','--env','-e','--privileged','/var/run/docker.sock'):
            self.assertNotIn(value,command)
        with self.assertRaises(ValueError):qualification.execution_args('toso-local','toso-local-red-probe-example','sha256:'+'a'*64)
        with self.assertRaises(ValueError):qualification.execution_args('delivery-kit-port2','unrelated-container','latest')

    def test_delayed_auto_removal_is_observed_without_restarting_or_deleting(self):
        with patch.object(qualification.subprocess,'check_output',side_effect=['exact-id\n','']) as read,\
                patch.object(qualification.time,'sleep') as pause:
            qualification.await_retirement('delivery-kit-port2-red-probe-example')
        self.assertEqual(read.call_count,2);pause.assert_called_once_with(0.25)
        for call in read.call_args_list:self.assertEqual(call.args[0][:3],['docker','ps','-aq'])

    def test_observation_deadline_preserves_handle_and_never_repeats_mutation(self):
        with patch.object(qualification.subprocess,'check_output',return_value='exact-id') as read,\
                patch.object(qualification.time,'monotonic',side_effect=[0,21]):
            with self.assertRaises(TimeoutError):qualification.await_retirement('delivery-kit-port2-red-probe-example')
        read.assert_called_once()


if __name__=='__main__':unittest.main()
