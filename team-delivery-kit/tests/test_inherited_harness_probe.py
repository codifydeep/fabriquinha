import hashlib,json,tempfile,unittest
from pathlib import Path
from inherited_harness_probe import literal_template,run


class InheritedHarnessProbeTests(unittest.TestCase):
    def test_extracts_literal_without_importing_or_executing_tests(self):
        source="raise RuntimeError('MUST NOT EXECUTE')\nNODE_HARNESS_TEMPLATE='const p = %(source_path)s; return p; }'"
        self.assertIn('return p;',literal_template(source,'NODE_HARNESS_TEMPLATE'))
        with self.assertRaises(ValueError):literal_template("NODE_HARNESS_TEMPLATE=unknown_call()",'NODE_HARNESS_TEMPLATE')

    def test_invalid_harness_does_not_become_product_failure_or_test_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);test=b"NODE_HARNESS_TEMPLATE='const p = %(source_path)s; return p; }'"
            product=b"'use strict'; const product = 1;"
            (root/'test_new.py').write_bytes(test);(root/'product.js').write_bytes(product)
            manifest=json.dumps(dict(files={name:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                for name,raw in [('test_new.py',test),('product.js',product)]}),sort_keys=True).encode()
            (root/'manifest.json').write_bytes(manifest);sha=hashlib.sha256(manifest).hexdigest()
            result=run(root,sha,'test_new.py','product.js','NODE_HARNESS_TEMPLATE')
            self.assertEqual(result['harness']['category'],'syntax_error')
            self.assertEqual(result['product']['category'],'valid')
            self.assertFalse(result['test_edits_authorized']);self.assertFalse(result['product_executed'])
            self.assertEqual((root/'test_new.py').read_bytes(),test)
            (root/'product.js').write_bytes(b'changed')
            with self.assertRaises(ValueError):run(root,sha,'test_new.py','product.js','NODE_HARNESS_TEMPLATE')
