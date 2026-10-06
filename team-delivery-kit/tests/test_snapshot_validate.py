import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
spec_copy = importlib.util.spec_from_file_location('snapshot_copy', ROOT / 'broker/snapshot_copy.py')
copy = importlib.util.module_from_spec(spec_copy)
spec_copy.loader.exec_module(copy)
spec_validate = importlib.util.spec_from_file_location('snapshot_validate', ROOT / 'broker/snapshot_validate.py')
validate = importlib.util.module_from_spec(spec_validate)
spec_validate.loader.exec_module(validate)


class SnapshotValidationTests(unittest.TestCase):
    def test_green_snapshot_passes_and_any_weakened_old_test_fails(self):
        fixture = ROOT / 'tests/fixtures/tdd'
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            target.mkdir()
            for name in copy.FILES:
                (source / name).write_bytes((fixture / name).read_bytes())
            (source / 'calc.py').write_text((source / 'calc.py').read_text() + '\n\ndef square(value):\n    return value * value\n')
            test_text = (source / 'test_calc.py').read_text().replace('from calc import add, multiply', 'from calc import add, multiply, square')
            (source / 'test_calc.py').write_text(test_text + '\n\nclass SquareTests(unittest.TestCase):\n    def test_square_positive(self):\n        self.assertEqual(square(4), 16)\n')
            with patch.object(copy, 'SOURCE', source), patch.object(copy, 'DESTINATION', target):
                copy.main()
            with patch.object(validate, 'DELIVERY', target), patch.object(validate, 'BASE_TEST', fixture / 'test_calc.py'), patch.object(validate, 'BASE_CODE', fixture / 'calc.py'):
                result = validate.validate()
                self.assertEqual(result['tests'], 7)
                with patch.dict(os.environ, {'REQUIRED_TESTS': 'test_square_negative'}):
                    with self.assertRaisesRegex(ValueError, 'required reviewer-requested test missing'):
                        validate.validate()
                (target / 'test_calc.py').chmod(0o600)
                (target / 'test_calc.py').write_text((target / 'test_calc.py').read_text().replace('self.assertEqual(multiply(-2, 4), -8)', 'self.assertTrue(True)'))
                with self.assertRaisesRegex(ValueError, 'snapshot hash mismatch'):
                    validate.validate()

    def test_rejects_weakened_baseline_with_consistent_manifest(self):
        fixture = ROOT / 'tests/fixtures/tdd'
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir(); target.mkdir()
            for name in copy.FILES:
                (source / name).write_bytes((fixture / name).read_bytes())
            (source / 'calc.py').write_text((source / 'calc.py').read_text() + '\n\ndef square(value):\n    return value * value\n')
            tests = (source / 'test_calc.py').read_text().replace('from calc import add, multiply', 'from calc import add, multiply, square')
            tests = tests.replace('self.assertEqual(multiply(-2, 4), -8)', 'self.assertTrue(True)')
            (source / 'test_calc.py').write_text(tests + '\n\nclass SquareTests(unittest.TestCase):\n    def test_square_positive(self):\n        self.assertEqual(square(4), 16)\n')
            with patch.object(copy, 'SOURCE', source), patch.object(copy, 'DESTINATION', target):
                copy.main()
            with patch.object(validate, 'DELIVERY', target), patch.object(validate, 'BASE_TEST', fixture / 'test_calc.py'), patch.object(validate, 'BASE_CODE', fixture / 'calc.py'):
                with self.assertRaisesRegex(ValueError, 'preexisting test modified'):
                    validate.validate()

    def test_rejects_skipped_new_test(self):
        fixture = ROOT / 'tests/fixtures/tdd'
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            target.mkdir()
            for name in copy.FILES:
                (source / name).write_bytes((fixture / name).read_bytes())
            (source / 'calc.py').write_text((source / 'calc.py').read_text() + '\n\ndef square(value):\n    return value * value\n')
            tests = (source / 'test_calc.py').read_text().replace('from calc import add, multiply', 'from calc import add, multiply, square')
            (source / 'test_calc.py').write_text(tests + '\n\nclass SquareTests(unittest.TestCase):\n    @unittest.skip("disabled")\n    def test_square_positive(self):\n        self.assertEqual(square(4), 16)\n')
            with patch.object(copy, 'SOURCE', source), patch.object(copy, 'DESTINATION', target):
                copy.main()
            with patch.object(validate, 'DELIVERY', target), patch.object(validate, 'BASE_TEST', fixture / 'test_calc.py'), patch.object(validate, 'BASE_CODE', fixture / 'calc.py'):
                with self.assertRaises(ValueError):
                    validate.validate()
