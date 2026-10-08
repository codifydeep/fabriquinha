import unittest
from model_review_smoke import command


class ReviewSmokeTests(unittest.TestCase):
    def test_probe_is_synthetic_scoped_readonly_and_not_a_product_approval(self):
        cmd = command('delivery-kit-port2', 'sha256:'+'a'*64, '93e73506-580a-4fb5-834c-0eced5c34692')
        self.assertIn('--rm', cmd)
        self.assertIn('--read-only', cmd)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests', cmd)
        script = cmd[-1]
        compile(script, '<review-probe>', 'exec')
        self.assertIn('DELIVERY_OBSERVED_FINDINGS_V1', script)
        self.assertIn('DELIVERY_TYPED_REVIEW_V1', script)
        self.assertIn('no file was actually read', script)
        self.assertIn('"delivery_approval":False', script)
        self.assertNotIn('/var/run/docker.sock', ' '.join(cmd))
        self.assertNotIn('register(', script)

    def test_invalid_execution_and_mutable_image_are_rejected(self):
        for execution, image in [('bad', 'sha256:'+'a'*64), ('93e73506-580a-4fb5-834c-0eced5c34692', 'worker:latest')]:
            with self.assertRaises(ValueError):
                command('delivery-kit-port2', image, execution)
