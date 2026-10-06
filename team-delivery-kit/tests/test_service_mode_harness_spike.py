import unittest
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
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

    def snapshot(self, directory):
        root = Path(directory)
        (root / 'tests').mkdir()
        (root / 'app/static').mkdir(parents=True)
        sources = {'tests/test_service_mode_indicator.py': 'NODE_HARNESS_TEMPLATE="fixed"',
                   'app/static/app.js': 'source', 'app/static/index.html': 'html',
                   'app/static/style.css': 'css'}
        for path, content in sources.items():
            (root / path).write_text(content)
        hashes = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in sources}
        (root / 'manifest.json').write_text(json.dumps({'files': {p: {'sha256': h} for p, h in hashes.items()}}))
        return root, hashes

    def output(self):
        return SimpleNamespace(returncode=0, stdout=json.dumps({'after_ok': {'text': 'Checking environment…', 'calls': 4},
            'pending_observed': {'text': 'Checking environment…', 'calls': 4}, 'after_deferred': 'Demo environment'}))

    def test_manifest_bound_inputs_never_count_as_red_or_approval(self):
        with TemporaryDirectory() as directory:
            root, hashes = self.snapshot(directory)
            with patch('broker.service_mode_harness_spike.subprocess.run', return_value=self.output()):
                proof = run(root, hashes['tests/test_service_mode_indicator.py'])
            self.assertEqual(proof['input_sha256'], hashes)
            self.assertFalse(proof['valid_red_green_receipt'])
            self.assertFalse(proof['delivery_approval'])
            self.assertEqual(proof['facts']['after_ok']['calls'], 4)

    def test_other_artifact_drift_rejected_before_execution(self):
        with TemporaryDirectory() as directory:
            root, hashes = self.snapshot(directory)
            (root / 'app/static/style.css').write_text('tampered')
            with patch('broker.service_mode_harness_spike.subprocess.run') as process:
                with self.assertRaisesRegex(ValueError, 'manifest drift'):
                    run(root, hashes['tests/test_service_mode_indicator.py'])
                process.assert_not_called()

    def test_changes_during_execution_are_rejected(self):
        with TemporaryDirectory() as directory:
            root, hashes = self.snapshot(directory)
            def alter(*args, **kwargs):
                (root / 'app/static/app.js').write_text('tampered')
                return self.output()
            with patch('broker.service_mode_harness_spike.subprocess.run', side_effect=alter):
                with self.assertRaisesRegex(ValueError, 'manifest drift'):
                    run(root, hashes['tests/test_service_mode_indicator.py'])
