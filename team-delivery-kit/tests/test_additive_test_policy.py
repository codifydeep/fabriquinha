import tempfile,hashlib,unittest
from pathlib import Path
import additive_test_policy as policy

CODE='import unittest\nclass Control(unittest.TestCase):\n    def test_c01_query_clearing_control(self):\n        self.assertTrue(True)\n'

class AdditiveTests(unittest.TestCase):
    def test_observed_rejected_structures_remain_prohibited(self):
        for code in ('from __future__ import annotations\n'+CODE,
                     'DRIVER = "constant"\n'+CODE,
                     CODE+'\nif __name__ == "__main__":\n    unittest.main()\n'):
            with self.assertRaises(ValueError):policy.validate(code,'C01')
    def test_exact_new_criterion_and_no_skip_or_side_effect_import(self):
        self.assertEqual(policy.validate(CODE,'C01'),CODE.encode())
        for code in ('// prose',CODE.replace('self.assertTrue(True)','self.skipTest("bad")'),
                CODE.replace('test_c01','test_c02'),CODE+'\nraise ValueError()\n', 'import os\n'+CODE):
            with self.assertRaises((ValueError,SyntaxError)):policy.validate(code,'C01')

    def test_fresh_read_creation_only_preserves_source_and_denies_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.py';source.write_text('X = 1\n');target=Path(folder)/'test_new.py'
            cfg={'path':str(target),'criterion':'C01','sources':{str(source):{'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}}
            args={'path':str(target),'content':CODE}
            with self.assertRaises(ValueError):policy.write(cfg,args,{})
            with self.assertRaises(ValueError):policy.write(cfg,dict(args,path=str(source)),{str(source):{1}})
            self.assertTrue(policy.write(cfg,args,{str(source):{1}})['verified'])
            with self.assertRaises(FileExistsError):policy.write(cfg,args,{str(source):{1}})
            self.assertEqual(source.read_text(),'X = 1\n')
