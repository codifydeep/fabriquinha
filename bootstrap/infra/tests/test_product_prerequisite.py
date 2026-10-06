import unittest
from product_prerequisite import validate,resume
from unittest.mock import Mock

class PrerequisiteTests(unittest.TestCase):
    def test_no_arbitrary_authority(self):
        good=dict(capability='backend',title='Runnable HTTP entry point',brief='Preserve every existing regression test and implement the missing runtime prerequisite with behavioral Red Green evidence and independent review.')
        validate(good)
        for bad in (dict(good,shell='exec'),dict(good,capability='deployment'),dict(good,brief='fix')):
            with self.assertRaises((ValueError,PermissionError)):validate(bad)
    def test_resume_waits_for_actual_integrated_source(self):
        c=Mock();c.get.return_value=None;c.db.execute.return_value=[]
        resume(c,'key',dict(prerequisite_task='child'))
        c.team_task.assert_not_called();c.put.assert_not_called()
