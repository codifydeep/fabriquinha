from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sequence_service


class SequenceServiceTests(unittest.TestCase):
    def test_terminal_block_does_not_restart_in_launchd_loop(self):
        import evalctl
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', {'DELIVERY_KIT_SEQUENCE_PLAN': 'unused'}), \
                    patch('sequence_service.load_plan', return_value={'name': 'TEST'}), \
                    patch('sequence_service.run_supervisor', return_value=1), \
                    patch('sequence_service.read_json', return_value={'stage': 'blocked'}), \
                    patch.object(evalctl, 'PRIVATE', Path(directory)):
                self.assertEqual(sequence_service.main(), 0)

    def test_nonterminal_failure_requests_launchd_restart(self):
        import evalctl
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', {'DELIVERY_KIT_SEQUENCE_PLAN': 'unused'}), \
                    patch('sequence_service.load_plan', return_value={'name': 'TEST'}), \
                    patch('sequence_service.run_supervisor', return_value=1), \
                    patch('sequence_service.read_json', return_value={'stage': 'working'}), \
                    patch.object(evalctl, 'PRIVATE', Path(directory)):
                self.assertEqual(sequence_service.main(), 1)


if __name__ == '__main__':
    unittest.main()
