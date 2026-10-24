import unittest
import os
from pathlib import Path
import tempfile
from supervisor_orphan_probe import probe,workload,write,read,LABEL,ISSUE


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

    def test_late_reconciliation_of_finished_fixture_is_not_a_second_workload(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'autonomy-status').mkdir();(root/'release').touch()
            write(root/'entered.json',[123])
            receipt=dict(label=LABEL,issue_id=ISSUE,stage='deployed_qa_passed',fixture_only=True)
            write(root/'autonomy-status'/(LABEL+'.json'),receipt)
            workload(root)
            self.assertEqual(read(root/'entered.json'),[123])
            self.assertEqual(read(root/'autonomy-status'/(LABEL+'.json')),receipt)

    def test_unfinished_fixture_still_executes_and_records_the_real_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'autonomy-status').mkdir();(root/'release').touch()
            write(root/'autonomy-status'/(LABEL+'.json'),dict(label=LABEL,issue_id=ISSUE,stage='accepted'))
            workload(root)
            self.assertEqual(read(root/'entered.json'),[os.getpid()])
            self.assertEqual(read(root/'autonomy-status'/(LABEL+'.json'))['stage'],'deployed_qa_passed')
