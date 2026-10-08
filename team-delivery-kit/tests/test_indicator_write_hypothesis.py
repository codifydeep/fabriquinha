import ast
import unittest
from service_mode_indicator_write_hypothesis import variant,EDITS,template


class IndicatorWriteHypothesisTests(unittest.TestCase):
    def source(self):
        return 'NODE_HARNESS_TEMPLATE = """'+ '\n'.join(old for old,new in EDITS)+'"""\nclass T:\n def test_a(self):\n  assert False\n'

    def test_only_literal_harness_changes_all_assertions_remain(self):
        source=self.source();changed=variant(source)
        before=ast.parse(source);after=ast.parse(changed)
        self.assertNotEqual(template(before).value,template(after).value)
        template(after).value=template(before).value
        self.assertEqual(ast.dump(before),ast.dump(after))
        for old,new in EDITS:self.assertIn(new,changed)

    def test_missing_duplicate_or_outside_template_anchor_rejected(self):
        source=self.source();old=EDITS[0][0]
        for invalid in (source.replace(old,'missing'),source.replace(old,old*2),source+'# '+old,
                        source.replace('NODE_HARNESS_TEMPLATE','OTHER_TEMPLATE')):
            with self.assertRaises(ValueError):variant(invalid)
