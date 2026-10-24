"""Distribution COPY closure for new imports, not a Docker/native qualification."""
from pathlib import Path
import shlex
import unittest

ROOT=Path(__file__).resolve().parents[1]


class DeliveryReviewImageSourcesTests(unittest.TestCase):
    def test_new_flat_controller_imports_are_packaged_in_both_builds_without_activation(self):
        expected={'broker/quality_delivery_review_handoff.py','broker/quality_delivery_review_validation.py',
            'broker/quality_delivery_review_launch.py','broker/quality_delivery_review_attestation.py',
            'broker/quality_delivery_revision.py','broker/quality_delivery_review_progress.py',
            'quality_delivery_review_policy.py','quality_delivery_review_verdict.py'}
        for name in ('Dockerfile.broker','Dockerfile.quality-v2-controller'):
            text=(ROOT/name).read_text();copied={}
            for line in text.splitlines():
                if not line.startswith('COPY '):continue
                parts=shlex.split(line)[1:]
                for source in parts[:-1]:copied[source]=parts[-1]
            with self.subTest(name=name):
                self.assertTrue(expected<=set(copied),str(sorted(expected-set(copied))))
                self.assertTrue(all(copied[p]=='/' for p in expected))
                for flag in ('BROKER_QUALITY_DELIVERY_REVIEW_ENABLED=1','BROKER_QUALITY_DELIVERY_REVISION_ENABLED=1'):
                    self.assertNotIn(flag,text)
