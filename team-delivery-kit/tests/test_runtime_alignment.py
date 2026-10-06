import unittest
from unittest.mock import patch

from runtime_alignment import compare, probe


class RuntimeAlignmentTests(unittest.TestCase):
    def test_exact_runtime_alignment_required(self):
        same = {'python': [3, 13, 5], 'sqlite': '3.53.4'}
        older = {'python': [3, 12, 14], 'sqlite': '3.40.1'}
        self.assertEqual(compare(same, same, same), 'aligned')
        self.assertEqual(compare(same, older, same), 'blocked_runtime_mismatch')
        self.assertEqual(compare(same, same, None), 'blocked_deployment_image_missing')

    def test_probe_rejects_mutable_image_reference(self):
        with self.assertRaisesRegex(ValueError, 'immutable'):
            probe('python:latest')

    @patch('runtime_alignment.subprocess.check_output', return_value='{"python":[3,13,5],"sqlite":"3.53.4"}')
    def test_probe_is_offline_and_read_only(self, command):
        image = 'sha256:' + 'a' * 64
        self.assertEqual(probe(image)['sqlite'], '3.53.4')
        args = command.call_args.args[0]
        self.assertIn('--network', args)
        self.assertIn('none', args)
        self.assertIn('--read-only', args)


if __name__ == '__main__':
    unittest.main()
