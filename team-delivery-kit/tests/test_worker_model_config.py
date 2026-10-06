import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    'worker_model_config_test', Path(__file__).parents[1] / 'broker/worker_model_config.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class WorkerModelConfigTests(unittest.TestCase):
    def test_execution_url_is_identity_scoped_and_known_config_can_migrate(self):
        first = '12345678-1234-1234-1234-123456789abc'
        second = '22345678-1234-1234-1234-123456789abc'
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            worker.install_config(home, first)
            self.assertIn('/executions/'+first+'/api/v1', (home/'config.yaml').read_text())
            worker.install_config(home, second)
            self.assertIn('/executions/'+second+'/api/v1', (home/'config.yaml').read_text())
            self.assertNotIn(first, (home/'config.yaml').read_text())
            with self.assertRaises(ValueError):
                worker.install_config(home, '../secret')
    def test_migrates_complete_read_config_to_one_api_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / 'config.yaml'
            target.write_text(worker.COMPLETE_READ_EXPECTED)
            worker.install_config(home)
            self.assertEqual(target.read_text(), worker.EXPECTED)
            self.assertEqual(target.read_text().count('api_max_retries: 1'), 1)
            worker.install_config(home)
            self.assertEqual(target.read_text(), worker.EXPECTED)

    def test_migrates_exact_previous_config_for_complete_bounded_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); target = home / 'config.yaml'
            target.write_text(worker.PREVIOUS_EXPECTED)
            worker.install_config(home)
            self.assertEqual(target.read_text(), worker.EXPECTED)
            self.assertIn('max_line_length: 65536', target.read_text())
            self.assertIn('file_read_max_chars: 65536', target.read_text())
            worker.install_config(home)

    def test_migrates_only_exact_previous_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / 'config.yaml'
            target.write_text(worker.LEGACY_EXPECTED)
            worker.install_config(home)
            self.assertEqual(target.read_text(), worker.EXPECTED)

    def test_migrates_exact_low_reasoning_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / 'config.yaml'
            target.write_text(worker.LOW_REASONING_EXPECTED)
            worker.install_config(home)
            self.assertEqual(target.read_text(), worker.EXPECTED)
            worker.install_config(home)
            self.assertEqual(target.read_text(), worker.EXPECTED)

    def test_rejects_unknown_config_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / 'config.yaml'
            target.write_text('unexpected: true\n')
            with self.assertRaisesRegex(ValueError, 'drift'):
                worker.install_config(home)
            self.assertEqual(target.read_text(), 'unexpected: true\n')

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            other = home / 'other.yaml'
            other.write_text(worker.LEGACY_EXPECTED)
            (home / 'config.yaml').symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'drift'):
                worker.install_config(home)
            self.assertEqual(other.read_text(), worker.LEGACY_EXPECTED)


if __name__ == '__main__':
    unittest.main()
