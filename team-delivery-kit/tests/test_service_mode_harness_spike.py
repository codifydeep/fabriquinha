import unittest
from broker.service_mode_harness_spike import extract_template, shape, run
from tempfile import TemporaryDirectory


class HarnessSchemaSpikeTests(unittest.TestCase):
    def test_extract_does_not_execute_module(self):
        self.assertEqual(extract_template('raise Exception("never execute")\nNODE_HARNESS_TEMPLATE="fixed"'), 'fixed')

    def test_nonliteral_or_duplicate_rejected(self):
        for source in ('NODE_HARNESS_TEMPLATE=call()',
                       'NODE_HARNESS_TEMPLATE="a"\nNODE_HARNESS_TEMPLATE="b"'):
            with self.assertRaises(ValueError):
                extract_template(source)

    def test_actual_shape_not_interpreted_as_success(self):
        result = shape({'after_ok': {'issued': 1, 'text': {'text': 'demo'}},
                        'pending_observed': {'calls': 1, 'text': {}},
                        'after_deferred': {'text': 'demo'}})
        self.assertFalse(result['after_ok']['has_calls'])
        self.assertTrue(result['after_ok']['has_issued'])
        self.assertEqual(result['after_ok']['text_type'], 'dict')
        self.assertEqual(result['after_deferred']['text_type'], 'str')

    def test_malformed_report_rejected(self):
        for report in ([], {}, {'after_ok': 'not object'}):
            with self.assertRaises(ValueError):
                shape(report)

    def test_hash_mismatch_prevents_execution(self):
        from pathlib import Path
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tests').mkdir()
            (root / 'app/static').mkdir(parents=True)
            (root / 'tests/test_service_mode_indicator.py').write_text('invalid python')
            (root / 'app/static/app.js').write_text('not executable')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                run(root, '0' * 64)
