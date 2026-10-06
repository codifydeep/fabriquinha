import json
import unittest
from unittest.mock import patch

from controller_broker_image import installed_image


class ControllerBrokerImageTests(unittest.TestCase):
    def test_uses_running_namespace_broker_digest(self):
        record = {'Image': 'sha256:' + 'a' * 64, 'State': {'Running': True},
                  'Config': {'Labels': {'com.docker.compose.project': 'test-project'}}}
        with patch('controller_broker_image.subprocess.check_output', return_value=json.dumps([record])):
            self.assertEqual(installed_image('test-project'), record['Image'])
        record['Config']['Labels']['com.docker.compose.project'] = 'other-project'
        with patch('controller_broker_image.subprocess.check_output', return_value=json.dumps([record])):
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                installed_image('test-project')
