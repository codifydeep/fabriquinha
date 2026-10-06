import json,unittest
from pathlib import Path
from unittest.mock import patch
import product_boundary
from product_test_sandbox import command

class LobbyConfigTests(unittest.TestCase):
    def test_role_distribution(self):
        data=json.loads((Path(__file__).parents[1]/'skills/manifest.json').read_text())
        self.assertEqual(len(data['profiles']),9)
        self.assertTrue(all('karpathy-guidelines' in s for s in data['profiles'].values()))
        self.assertNotIn('frontend-design',data['profiles']['backend_data'])
        self.assertNotIn('3d-web-experience',data['profiles']['quality_security'])
    def test_real_product_context_is_not_rehearsal(self):
        state=dict(task='t_x',mode='implementation')
        cfg=dict(scope='truco-lobby',cards={'t_x':{'brief':'Actual health foundation','author':'backend_data','reviewer':'techlead'}})
        with patch('review_boundary.worker_state',return_value=state),patch.object(product_boundary,'config',return_value=cfg):
            parts=product_boundary.scoped_parts()
        self.assertIn('real Truco',parts['stable'])
        self.assertNotIn('rehearsal',parts['context'])
    def test_ts_command_fixed_and_isolated(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'test.ts').write_text('test')
            cmd=command(d,'sha256:'+'a'*64,'check','lobby-ts')
        self.assertIn('--network=none',cmd)
        self.assertIn('--read-only',cmd)
        self.assertEqual(cmd[-1],'/opt/toolchain/run.mjs')
        self.assertNotIn('/var/run/docker.sock',' '.join(cmd))
    def test_unknown_runner_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'a').write_text('x')
            with self.assertRaises(ValueError):command(d,'sha256:'+'a'*64,'x','shell')
