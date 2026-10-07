"""Preparator qualification only; no worker grant or protocol activation."""
import ast,hashlib,unittest
from surgical_test_edit import prepare_template_lines,FileBudgetError,DriverSyntaxError,_tests


class TemplateLinePreparationTests(unittest.TestCase):
    SOURCE=('import unittest\nCONTROL="immutable"\nNODE_HARNESS_TEMPLATE=r"""\n'
        'const path = %(source_path)s;\n'
        'const pending = "pending";\n'
        'const terminal = pending;\n'
        '"""\nclass Tests(unittest.TestCase):\n'
        ' def test_a(self):\n  self.assertEqual(CONTROL,"immutable")\n'
        ' def test_b(self):\n  self.assertFalse(False)\n').encode()

    def envelope(self,source=None,edits=None):
        return dict(expected_sha256=hashlib.sha256(source or self.SOURCE).hexdigest(),
            edits=edits or [dict(start_line=6,end_line=6,new='const terminal = "done";\n')])

    def test_only_literal_changes_and_all_test_bodies_remain_identical(self):
        before=self.SOURCE
        result=prepare_template_lines(before,self.envelope())
        self.assertEqual(_tests(ast.parse(before)),_tests(ast.parse(result)))
        self.assertEqual(result,before.replace(b'const terminal = pending;',b'const terminal = "done";'))
        self.assertEqual(before,self.SOURCE)

    def test_multiple_ranges_use_original_line_numbers_not_intermediate_output(self):
        edits=[dict(start_line=5,end_line=5,new='const pending = "pending";\n// extra driver line\n'),
            dict(start_line=6,end_line=6,new='const terminal = "done";\n')]
        result=prepare_template_lines(self.SOURCE,self.envelope(edits=edits))
        self.assertIn(b'// extra driver line\nconst terminal = "done";',result)
        self.assertEqual(_tests(ast.parse(self.SOURCE)),_tests(ast.parse(result)))

    def test_scope_hash_shape_overlap_and_discovery_boundaries_are_enforced(self):
        args=self.envelope();args['expected_sha256']='0'*64
        cases=[args]
        for start,end,new in [(1,1,'import os\n'),(2,2,'CONTROL="changed"\n'),(3,3,''),(7,7,''),
                              (10,10,'  self.assertTrue(True)\n'),(6,999,''),(True,6,''),
                              (6,6,'const terminal = pending;\n')]:
            cases.append(self.envelope(edits=[dict(start_line=start,end_line=end,new=new)]))
        cases.append(self.envelope(edits=[dict(start_line=6,end_line=6,new='// a\n'),dict(start_line=5,end_line=6,new='// b\n')]))
        cases.append(self.envelope(edits=[dict(start_line=5,end_line=6,new='// a\n'),dict(start_line=6,end_line=6,new='// b\n')]))
        cases.append(self.envelope(edits=[dict(start_line=6,end_line=6,new='// a\n',template_name='OTHER')]))
        for args in cases:
            with self.subTest(args=args),self.assertRaises(ValueError):prepare_template_lines(self.SOURCE,args)

    def test_quote_escape_cannot_modify_python_outside_the_literal(self):
        args=self.envelope(edits=[dict(start_line=6,end_line=6,
            new='"""\nCONTROL="changed"\nEVIL=r"""\n')])
        with self.assertRaises((ValueError,SyntaxError)):prepare_template_lines(self.SOURCE,args)

    def test_node_syntax_check_and_unchanged_original_on_failure(self):
        args=self.envelope(edits=[dict(start_line=6,end_line=6,new='const terminal = ;\n')])
        with self.assertRaises(DriverSyntaxError):prepare_template_lines(self.SOURCE,args)
        self.assertIn(b'const terminal = pending;',self.SOURCE)

    def test_utf8_budget_is_not_increased_by_line_mode(self):
        source=self.SOURCE+b'#'+b' '*32400+b'\n'
        self.assertLess(len(source),32768)
        args=self.envelope(source,edits=[dict(start_line=6,end_line=6,new='// '+'é'*150+'\nconst terminal = "done";\n')])
        with self.assertRaises(FileBudgetError) as caught:prepare_template_lines(source,args)
        self.assertEqual(caught.exception.source_bytes,len(source))
        self.assertGreater(caught.exception.proposed_bytes,32768)
        self.assertIn(b'const terminal = pending;',source)
