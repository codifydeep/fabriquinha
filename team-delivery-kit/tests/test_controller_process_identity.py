from pathlib import Path
import unittest
from unittest.mock import patch
import controller_process_identity as identity


class ControllerProcessIdentityTests(unittest.TestCase):
    def test_actual_mac_framework_interpreter_is_an_exact_identity_not_basename(self):
        framework='/framework/Python.app/Contents/MacOS/Python'
        with (patch.object(identity.sys,'executable','/framework/bin/python3'),
              patch.object(identity.subprocess,'check_output',return_value=framework+'\n'),
              patch.object(Path,'is_file',return_value=True)):
            allowed=identity.interpreters()
        script=Path('/project/portable_delivery.py');label='EXACT-1'
        self.assertTrue(identity.matches(framework+' -u '+str(script)+' --managed-label '+label,script,label,allowed))
        self.assertFalse(identity.matches('/other/Python -u '+str(script)+' --managed-label '+label,script,label,allowed))
        self.assertFalse(identity.matches(framework+' -u '+str(script)+' --managed-label OTHER',script,label,allowed))
        self.assertFalse(identity.matches(framework+' -u /other.py --managed-label '+label,script,label,allowed))
