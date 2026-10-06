import importlib.util
from pathlib import Path
import unittest

import acp_wrapper
import model_policy
import model_proxy
import register_team


def load(relative):
    path = Path(__file__).parents[1] / relative
    spec = importlib.util.spec_from_file_location(relative.replace('/', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModelPolicyTests(unittest.TestCase):
    def test_all_runtime_components_share_one_model_policy(self):
        transport = load('broker/acp_transport.py')
        worker = load('broker/worker_model_config.py')
        self.assertEqual({acp_wrapper.MODEL, model_proxy.MODEL,
                          register_team.MODEL, transport.MODEL}, {model_policy.MODEL})
        self.assertIn(model_policy.MODEL, worker.EXPECTED)
        self.assertIn(model_policy.PROXY_BASE_URL, worker.EXPECTED)
        self.assertIn('reasoning_effort: low', worker.EXPECTED)
        self.assertNotIn(model_policy.PLACEHOLDER_KEY, worker.EXPECTED)


if __name__ == '__main__':
    unittest.main()
