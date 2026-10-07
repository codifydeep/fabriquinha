import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from broker import service_mode_observation_hypothesis as probe


class ObservationHypothesisTests(unittest.TestCase):
    def test_unique_literal_intervention_preserves_all_test_bodies(self):
        source = 'NODE_HARNESS_TEMPLATE = """'+probe.OLD+'"""\nclass Tests:\n def test_a(self):\n  assert False\n'
        result = probe.variant(source)
        self.assertEqual(result, source.replace(probe.OLD, probe.NEW))
        for invalid in [source.replace(probe.OLD,'different'),source.replace(probe.OLD,probe.OLD*2),
                        source+'# '+probe.OLD,source.replace('"""'+probe.OLD+'"""','call()')]:
            with self.assertRaises(ValueError):probe.variant(invalid)

    def snapshot(self, root):
        path = root / probe.calibration.TEST
        path.parent.mkdir()
        path.write_text('NODE_HARNESS_TEMPLATE = """'+probe.OLD+'"""\n')
        product=root/probe.calibration.PRODUCT;product.parent.mkdir(parents=True);product.write_text('original product')
        entries={str(p.relative_to(root)):dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in (path,product)}
        raw=json.dumps(dict(files=entries)).encode();(root/'manifest.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def rejected(self):
        return dict(status='rejected',phase='positive_reference',facts=dict(positive=dict(
            tests=15,failures=2,failed_methods=sorted(probe.FAILED),errors=0,skipped=0,
            expected_failures=0,unexpected_successes=0)))

    def test_disposable_variant_never_becomes_original_red_or_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=self.snapshot(root)
            original={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            def observe(path, sha):
                probe.verify_snapshot(path,sha)
                if path==root:return self.rejected()
                self.assertNotEqual(sha,manifest)
                self.assertIn(probe.NEW,(path/probe.calibration.TEST).read_text())
                self.assertEqual((path/probe.calibration.PRODUCT).read_text(),'original product')
                return dict(status='passed',positive=dict(tests=15),negative_controls={})
            with patch.object(probe,'observe',side_effect=observe):result=probe.run(root,manifest)
            self.assertEqual(result['status'],'supported')
            for key in ('valid_red_green_receipt','author_retry_authorized','delivery_approval'):
                self.assertFalse(result[key])
            self.assertTrue(result['diagnostic_copy_only'])
            self.assertEqual(original,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_other_failure_is_not_reinterpreted_as_this_hypothesis(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=self.snapshot(root)
            for result in [dict(status='passed'),{**self.rejected(),'phase':'compile'},
                           dict(status='rejected',phase='positive_reference',facts=dict(positive=dict(tests=15,failures=1)))]:
                with patch.object(probe,'observe',return_value=result):
                    with self.assertRaises(ValueError):probe.run(root,manifest)

    def test_failing_variant_retains_refuted_hypothesis(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=self.snapshot(root)
            with patch.object(probe,'observe',return_value=self.rejected()):result=probe.run(root,manifest)
            self.assertEqual(result['status'],'refuted');self.assertFalse(result['delivery_approval'])
