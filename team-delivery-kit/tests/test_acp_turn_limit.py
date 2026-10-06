import unittest
from broker.install_acp_turn_limit import ANCHOR, adapt


class ACPTurnLimitTests(unittest.TestCase):
    def source(self):
        return ('class Manager:\n    def _make_agent(self, model=None):\n'
                '        default_model="fixed-model"\n        kwargs = {\n'
                + ANCHOR + '        }\n        return AIAgent(**kwargs)\n')

    def test_constructor_passes_actual_limit_without_paid_execution(self):
        namespace = {'AIAgent': lambda **kwargs: kwargs}
        exec(adapt(self.source()), namespace)
        result = namespace['Manager']()._make_agent()
        self.assertEqual(result['max_iterations'], 40)
        self.assertEqual(result['model'], 'fixed-model')

    def test_unknown_factory_duplicate_anchor_or_double_patch_rejected(self):
        for source in ('changed', self.source().replace('_make_agent', 'other_factory'),
                       self.source() + ANCHOR, adapt(self.source())):
            with self.subTest(source=source[:40]), self.assertRaises(ValueError):
                adapt(source)
