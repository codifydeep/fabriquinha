import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from surgical_test_edit import prepare, edit_file


class SurgicalTestEditTests(unittest.TestCase):
    source='import pytest\n\ndef test_behavior():\n    assert 1 == 2\n'

    def envelope(self):
        return {'expected_sha256':hashlib.sha256(self.source.encode()).hexdigest(),
                'edits':[{'old':'import pytest','new':'import unittest'},
                         {'old':'def test_behavior():\n    assert 1 == 2',
                          'new':'class Behavior(unittest.TestCase):\n    def test_behavior(self):\n        assert 1 == 2'}]}

    def test_adapts_discovery_without_changing_test_body(self):
        result=prepare(self.source.encode(),self.envelope())
        self.assertIn(b'unittest.TestCase',result)
        self.assertIn(b'assert 1 == 2',result)
        self.assertNotIn(b'pytest',result)

    def test_rejects_stale_hash_ambiguous_edit_and_changed_assertion(self):
        for mutation in ('hash','ambiguous','assertion','no_discovery','skip'):
            with self.subTest(mutation=mutation):
                args=self.envelope()
                if mutation=='hash':args['expected_sha256']='0'*64
                elif mutation=='ambiguous':args['edits'][0]['old']='not found'
                elif mutation=='assertion':args['edits'][1]['new']=args['edits'][1]['new'].replace('1 == 2','True')
                elif mutation=='no_discovery':args['edits']=args['edits'][:1]
                elif mutation=='skip':args['edits'][1]['new']=args['edits'][1]['new'].replace('    def test_','    @unittest.skip("ignore")\n    def test_')
                with self.assertRaises(ValueError):prepare(self.source.encode(),args)

    def test_rejects_method_removal_and_test_body_statement_removal(self):
        source=self.source.replace('    assert','    observed = 1\n    assert')
        args=self.envelope();args['expected_sha256']=hashlib.sha256(source.encode()).hexdigest()
        args['edits'][1]['old']=args['edits'][1]['old'].replace('    assert','    observed = 1\n    assert')
        with self.assertRaises(ValueError):prepare(source.encode(),args)
        args=self.envelope();args['edits'][1]['new']='VALUE = 1'
        with self.assertRaises(ValueError):prepare(self.source.encode(),args)

    def test_file_requires_observed_read_and_preserves_bytes_on_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();path=root/'test_new.py';path.write_text(self.source)
            with self.assertRaises(ValueError):edit_file(path,self.envelope(),root=root,observed_read=False)
            self.assertEqual(path.read_text(),self.source)
            receipt=edit_file(path,self.envelope(),root=root,observed_read=True)
            self.assertTrue(receipt['verified']);self.assertTrue(receipt['test_bodies_preserved'])
            self.assertEqual(receipt['before_sha256'],self.envelope()['expected_sha256'])
            self.assertEqual(receipt['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertFalse(receipt['delivery_approval'])
            self.assertRaises(ValueError,edit_file,path,self.envelope(),root=root,observed_read=True)

    def test_symlink_never_modified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py';target.write_text(self.source)
            link=root/'test_link.py';link.symlink_to(target)
            with self.assertRaises(ValueError):edit_file(link,self.envelope(),root=root,observed_read=True)
            self.assertEqual(target.read_text(),self.source)
