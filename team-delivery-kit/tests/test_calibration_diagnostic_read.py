import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from calibration_diagnostic_read import page


class DiagnosticReadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'candidate';self.root.mkdir()
        self.path=self.root/'app.html';self.path.write_text('one\ntwo\n')
        self.manifest=json.dumps({'files':{'app.html':{
            'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),'bytes':8}}}).encode()
        (self.root/'manifest.json').write_bytes(self.manifest)
        self.hash=hashlib.sha256(self.manifest).hexdigest()
        self.args={'path':'/evidence/candidate/app.html','offset':1,'limit':1}
        self.patcher=patch('calibration_diagnostic_read.Path',return_value=self.base)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_only_requested_page_is_returned_with_snapshot_hashes(self):
        result=page(self.args,self.hash);out=json.loads(result['output'])
        self.assertEqual(out,{'total_lines':2,'content':'1|one'})
        self.assertEqual(result['manifest_sha256'],self.hash)

    def test_modified_bytes_or_manifest_cannot_be_read(self):
        with self.assertRaises(ValueError):page(self.args,'a'*64)
        self.path.write_text('bad\ntwo\n')
        with self.assertRaises(ValueError):page(self.args,self.hash)

    def test_symlinks_and_undeclared_or_secret_paths_are_rejected(self):
        self.path.unlink();self.path.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):page(self.args,self.hash)
        for name in ('missing.html','.env','credential.json','../app.html'):
            with self.assertRaises(ValueError):
                page(dict(self.args,path='/evidence/candidate/'+name),self.hash)

    def test_outside_root_and_invalid_page_bounds_are_rejected(self):
        for args in (dict(self.args,path='/secret/openrouter.key'),
                     dict(self.args,offset=0),dict(self.args,offset=3),dict(self.args,limit=101)):
            with self.assertRaises(ValueError):page(args,self.hash)

    def test_manifest_cannot_be_a_symlink(self):
        manifest=self.root/'manifest.json';manifest.unlink()
        manifest.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):page(self.args,self.hash)
