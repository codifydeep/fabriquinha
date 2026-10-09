import json
import unittest
from controller_dispatch_admission import maintenance_active


class DispatchAdmissionTests(unittest.TestCase):
    def test_active_barrier_defers_and_released_observation_does_not(self):
        self.assertFalse(maintenance_active('delivery-kit-test',read=lambda _:'null'))
        for stage in ('draining','sealed'):
            self.assertTrue(maintenance_active('delivery-kit-test',read=lambda _:json.dumps(
                dict(namespace='delivery-kit-test',stage=stage,operation_id='operation'))))

    def test_wrong_owner_or_incomplete_state_never_admits(self):
        for value in ({},{'namespace':'other','stage':'sealed','operation_id':'operation'},
                {'namespace':'delivery-kit-test','stage':'released','operation_id':'operation'}):
            with self.assertRaises(ValueError):maintenance_active('delivery-kit-test',read=lambda _:json.dumps(value))

    def test_uses_only_fixed_status_operation_and_rejects_broad_namespace(self):
        def read(command):
            self.assertEqual(command[-2:],['status',''])
            self.assertIn('delivery-kit-test-execution-broker-1',command)
            return 'null'
        self.assertFalse(maintenance_active('delivery-kit-test',read=read))
        with self.assertRaises(ValueError):maintenance_active('../../other',read=read)
