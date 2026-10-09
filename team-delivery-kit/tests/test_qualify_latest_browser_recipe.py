import unittest
from qualify_latest_browser_recipe import command


class LatestCalibrationSandboxTests(unittest.TestCase):
    def test_fixed_offline_readonly_sandbox_never_mounts_product_or_credentials(self):
        args=command('sha256:'+'a'*64)
        self.assertIn('--rm',args);self.assertIn('--read-only',args)
        self.assertEqual(args[args.index('--network')+1],'none')
        self.assertEqual(args[args.index('--user')+1],'10000:10000')
        mounts=[args[i+1] for i,value in enumerate(args) if value=='--mount']
        self.assertEqual(len(mounts),2)
        self.assertTrue(all(mount.endswith(',readonly') for mount in mounts))
        self.assertNotIn('/var/run/docker.sock',' '.join(args))
        self.assertNotIn('.local-port2',' '.join(args))
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',args)

    def test_image_must_be_immutable(self):
        for image in ('latest','repo:tag','sha256:bad','a'*64):
            with self.assertRaises(ValueError):command(image)
