import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from surgical_test_edit import prepare_template,edit_file,marker_config,typed_schema

SOURCE=b'import unittest\nCONTROL="unchanged"\nNODE_HARNESS_TEMPLATE=r"""\nconst source = %(source_path)s;\nasync function drive(){\n const before="pending";\n const after_ok = {text: before};\n}\n"""\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'


class TemplateOnlyEditTests(unittest.TestCase):
    def args(self,old='const after_ok = {text: before};',new='const after_ok = {text: "terminal"};'):
        return dict(expected_sha256=hashlib.sha256(SOURCE).hexdigest(),edits=[dict(old=old,new=new)])

    def test_only_literal_changes_with_all_other_ast_preserved(self):
        result=prepare_template(SOURCE,self.args())
        self.assertIn(b'{text: "terminal"}',result)
        self.assertIn(b'def test_ok(self): self.assertTrue(True)',result)
        for args in [self.args('CONTROL="unchanged"','CONTROL="changed"'),
                     self.args('self.assertTrue(True)','pass'),
                     self.args(new='const after_ok = {text: ;'),
                     self.args('NODE_HARNESS_TEMPLATE','OTHER_TEMPLATE')]:
            with self.assertRaises((ValueError,SyntaxError)):prepare_template(SOURCE,args)

    def test_locked_file_preserves_bytes_on_denial_and_rejects_stale_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'test_template.py';path.write_bytes(SOURCE)
            for read,args in [(False,self.args()),(True,self.args(new='const after_ok = {text: ;')),
                              (True,self.args('CONTROL="unchanged"','CONTROL="changed"')),
                              (True,self.args('self.assertTrue(True)','pass'))]:
                with self.assertRaises(ValueError):edit_file(path,args,root=root,observed_read=read,
                                                           required_uid=os.getuid(),template_only=True)
                self.assertEqual(path.read_bytes(),SOURCE)
            result=edit_file(path,self.args(),root=root,observed_read=True,required_uid=os.getuid(),template_only=True)
            self.assertTrue(result['test_bodies_preserved']);self.assertFalse(result['delivery_approval'])
            changed=path.read_bytes()
            with self.assertRaises(ValueError):edit_file(path,self.args(),root=root,observed_read=True,template_only=True)
            self.assertEqual(path.read_bytes(),changed)

    def test_v5_marker_uses_actual_typed_tool_without_agent_selected_template_name(self):
        cfg=marker_config(dict(messages=[dict(role='user',content='DELIVERY_SURGICAL_TEST_V5:/workspace/test_template.py:'+'a'*64+'\n')]))
        self.assertEqual(cfg['protocol'],'typed_template_v5')
        schema=typed_schema(cfg)
        self.assertEqual(schema['name'],'surgical_test_edit')
        self.assertNotIn('template_name',schema['parameters']['properties'])
