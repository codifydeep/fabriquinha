import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from calibration_node_path_probe import run,binding,validate

SOURCE='''from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
APP_JS=ROOT / 'app' / 'app.js'
INDEX_HTML=ROOT / 'app' / 'index.html'
NODE_HARNESS="const SOURCE = fs.readFileSync(%(source_path)s, 'utf8');"
class Tests:
 def method(self):
  text=INDEX_HTML.read_text()
  program=NODE_HARNESS % {'source_path':json.dumps(str(APP_JS)),'source_name':json.dumps(str(APP_JS))}
'''


class NodePathProbeTests(unittest.TestCase):
    def test_actual_node_read_tracks_path_substitution_without_running_product_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);files={'tests/test_probe.py':SOURCE,'app/app.js':'unchanged script','app/index.html':'unchanged markup'}
            for name,value in files.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            manifest=json.dumps({'files':{name:dict(bytes=len(v.encode()),sha256=hashlib.sha256(v.encode()).hexdigest()) for name,v in files.items()}},sort_keys=True)
            (root/'manifest.json').write_text(manifest);sha=hashlib.sha256(manifest.encode()).hexdigest()
            tests={'tests/test_probe.py':hashlib.sha256(SOURCE.encode()).hexdigest()}
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            value=run(root,sha,tests);validate(value,dict(prepared=dict(manifest_sha256=sha,test_sha256=tests),test_files=list(tests)))
            self.assertEqual(before,{p:p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertEqual(value['bindings']['tests/test_probe.py']['attribute'],'APP_JS')
            self.assertFalse(value['product_tests_executed']);self.assertFalse(value['calibration_approved'])

    def test_unknown_format_expressions_and_modified_read_statement_do_not_execute(self):
        paths={'APP_JS':'app/app.js','INDEX_HTML':'app/index.html'}
        for source in (SOURCE.replace('json.dumps(str(APP_JS))','dangerous(APP_JS)'),
                SOURCE.replace('fs.readFileSync','fs.writeFileSync'),SOURCE+SOURCE):
            with self.assertRaises(ValueError):binding(source,paths)
