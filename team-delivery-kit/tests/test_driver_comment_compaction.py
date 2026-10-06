import ast
import unittest
from broker.driver_comment_compaction import compact


class DriverCommentCompactionTests(unittest.TestCase):
    def test_comments_removed_but_code_literals_and_python_tests_preserved(self):
        source=b'''import unittest
DRIVER_BODY = r"""// verbose line comment
const url="https://example.test//literal";
/* big block comment */ const value=1;
// another comment
// C10STATUS preserved handoff anchor
console.log(url,value);
"""
class Tests(unittest.TestCase):
    def test_original(self):
        self.assertEqual(1,1)
'''
        result,proof=compact(source)
        self.assertLess(len(result),len(source))
        self.assertEqual(proof['comments_removed'],3)
        self.assertTrue(proof['javascript_ast_preserved']);self.assertTrue(proof['non_driver_ast_preserved'])
        self.assertFalse(proof['delivery_approval'])
        self.assertIn(b'https://example.test//literal',result)
        self.assertIn(b'self.assertEqual(1,1)',result)
        self.assertIn(b'C10STATUS preserved handoff anchor',result)
        self.assertGreater(result.count(b'\n'),6)
        ast.parse(result)
    def test_parser_rejects_changes_to_multiline_template_literal(self):
        with self.assertRaisesRegex(ValueError,'AST-preserving'):
            compact(b'DRIVER_BODY = "const x=`a\\n   \\nb`; //comment"\n')
    def test_invalid_javascript_is_not_repaired_by_compaction(self):
        with self.assertRaisesRegex(ValueError,'AST-preserving'):
            compact(b'DRIVER_BODY = "Promise.resolve().then(() => { //comment"\n')
