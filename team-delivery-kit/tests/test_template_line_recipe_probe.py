import hashlib,unittest
from broker import template_line_recipe_probe as probe


class TemplateLineRecipeProbeTests(unittest.TestCase):
    def source(self):
        return ('import unittest\nNODE_HARNESS_TEMPLATE=r"""\n'+probe.OLD+'\n"""\n'
            'class Tests(unittest.TestCase):\n def test_a(self): self.assertTrue(True)\n').encode()

    def test_line_recipe_is_exactly_the_validated_intervention_not_a_new_variant(self):
        source=self.source();args,result=probe.recipe(source)
        self.assertEqual(result,source.replace(probe.OLD.encode(),probe.NEW.encode(),1))
        self.assertEqual(args['expected_sha256'],hashlib.sha256(source).hexdigest())
        self.assertEqual(args['edits'][0]['start_line'],3)
        self.assertEqual(args['edits'][0]['end_line'],3)
        self.assertLess(len(result),len(source))
        self.assertIn(b'self.assertTrue(True)',result)

    def test_missing_duplicate_and_outside_template_anchors_fail_closed(self):
        original=self.source()
        for bad in (original.replace(probe.OLD.encode(),b'different'),
                    original.replace(probe.OLD.encode(),(probe.OLD*2).encode()),
                    original.replace(b'NODE_HARNESS_TEMPLATE',b'UNRELATED')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):probe.recipe(bad)
