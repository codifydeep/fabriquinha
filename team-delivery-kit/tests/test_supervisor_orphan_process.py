import unittest
from supervisor_orphan_probe import probe


class RealOrphanProcessTests(unittest.TestCase):
    def test_killed_supervisor_does_not_restart_live_controller_workload(self):
        result=probe()
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['initial_exit_code'],-9)
        self.assertEqual(result['workload_executions'],1)
        self.assertEqual(result['unexpected_exits'],0)
        self.assertTrue(result['busy_observed'])
        self.assertTrue(result['original_child_completed'])
        self.assertEqual(result['model_calls'],0)
        self.assertFalse(result['application_delivery_proven'])
