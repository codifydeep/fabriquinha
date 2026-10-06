import hashlib
import tempfile
from pathlib import Path
import unittest
from surgical_test_edit import prepare_driver_lines,edit_file,typed_schema,validate_typed,marker_config

SOURCE=b'import unittest\nDRIVER_PREAMBLE="unchanged"\nDRIVER_BODY=r"""\n// duplicate\n// duplicate\nPromise.resolve();\n"""\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'

class DriverLineEditTests(unittest.TestCase):
    def args(self,edits):return {'expected_sha256':hashlib.sha256(SOURCE).hexdigest(),'edits':edits}

    def test_repeated_text_can_be_selected_by_original_line_without_fuzzy_matching(self):
        result=prepare_driver_lines(SOURCE,self.args([{'start_line':4,'end_line':4,'new':'// changed\n'},
            {'start_line':6,'end_line':6,'new':'Promise.resolve().then(()=>{});\n'}]))
        self.assertEqual(result.count(b'// duplicate'),1)
        self.assertIn(b'// changed\n',result)
        self.assertEqual(result.split(b'"""')[2],SOURCE.split(b'"""')[2])

    def test_ranges_and_scope_fail_closed(self):
        for edits in ([{'start_line':3,'end_line':4,'new':''}],
            [{'start_line':7,'end_line':7,'new':''}],
            [{'start_line':9,'end_line':9,'new':' def test_ok(self): pass\n'}],
            [{'start_line':4,'end_line':5,'new':''},{'start_line':5,'end_line':6,'new':''}],
            [{'start_line':6,'end_line':6,'new':''},{'start_line':4,'end_line':4,'new':''}],
            [{'start_line':True,'end_line':4,'new':''}],
            [{'start_line':4,'end_line':4,'new':'// duplicate\n'}],
            [{'start_line':6,'end_line':6,'new':'Promise.resolve().then(()=>{\n'}],
            [{'start_line':4,'end_line':4,'new':'x'*4097}]):
            with self.subTest(edits=edits),self.assertRaises((ValueError,SyntaxError)):
                prepare_driver_lines(SOURCE,self.args(edits))
        args=self.args([{'start_line':4,'end_line':4,'new':'// changed\n'}]);args['expected_sha256']='0'*64
        with self.assertRaises(ValueError):prepare_driver_lines(SOURCE,args)

    def test_late_failure_never_writes_and_read_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'test_new.py';path.write_bytes(SOURCE)
            args=self.args([{'start_line':4,'end_line':4,'new':'// changed\n'},
                {'start_line':6,'end_line':6,'new':'Promise.resolve().then(()=>{\n'}])
            for observed in (False,True):
                with self.assertRaises(ValueError):edit_file(path,args,root=root,observed_read=observed,driver_only=True,line_ranges=True)
                self.assertEqual(path.read_bytes(),SOURCE)

    def test_schema_and_marker_are_explicit_not_legacy_old_new(self):
        config=marker_config({'messages':[{'role':'user','content':'DELIVERY_SURGICAL_TEST_V4:/workspace/test_new.py:'+hashlib.sha256(SOURCE).hexdigest()}]})
        self.assertEqual(config['protocol'],'typed_driver_lines_v4')
        item=typed_schema(config)['parameters']['properties']['edits']['items']
        self.assertEqual(set(item['required']),{'start_line','end_line','new'})
        args={'path':config['path'],**self.args([{'start_line':4,'end_line':4,'new':'// changed\n'}])}
        validate_typed(args,config)
        with self.assertRaises(ValueError):validate_typed(dict(args,edits=[{'old':'duplicate','new':'changed'}]),config)
