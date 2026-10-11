import copy
from pathlib import Path
import unittest
from generic_harness_calibration import digest
from generic_calibration_seam_probe import run
import test_generic_harness_calibration_v2 as samples


class SeamProbeTests(unittest.TestCase):
    def setUp(self):
        s=samples.MultiPathCalibrationTests();s.setUp();self.addCleanup(s.doCleanups);self.s=s

    def proof(self):
        return run(self.s.candidate,self.s.policy['candidate_manifest_sha256'],self.s.policy['test_sha256'])

    def test_two_existing_path_globals_are_detected_without_import_or_write(self):
        before={p:p.read_bytes() for p in self.s.candidate.rglob('*') if p.is_file()}
        proof=self.proof()
        self.assertEqual(proof['paths'],{'tests/test_ui.py':{'APP_JS':'app/app.js','INDEX_HTML':'app/index.html'}})
        self.assertEqual(set(proof['product_sha256']),{'app/app.js','app/index.html'})
        self.assertIs(proof['tests_executed'],False);self.assertIs(proof['execution_authorized'],False)
        self.assertEqual(before,{p:p.read_bytes() for p in self.s.candidate.rglob('*') if p.is_file()})

    def test_ast_only_accepts_verified_root_shapes_and_never_executes_top_level_code(self):
        path='tests/test_ui.py';text=(self.s.candidate/path).read_text()
        text='raise RuntimeError("never import me")\n'+text.replace('Path(__file__).parents[1]','ROOT')
        text='from pathlib import Path\nROOT=Path(__file__).resolve().parent.parent\n'+text
        sha,files=self.s.snapshot(self.s.candidate,{path:text,'app/app.js':'js','app/index.html':'html'})
        proof=run(self.s.candidate,sha,{path:files[path]['sha256']})
        self.assertEqual(len(proof['paths'][path]),2)

    def test_single_path_foreign_root_and_snapshot_drift_are_rejected(self):
        path='tests/test_ui.py';text=(self.s.candidate/path).read_text()
        for changed in (text.replace('INDEX_HTML=Path(__file__).parents[1]/"app/index.html"','INDEX_HTML="not a Path"'),
                text.replace('Path(__file__).parents[1]','Path("/private")')):
            sha,files=self.s.snapshot(self.s.candidate,{path:changed,'app/app.js':'js','app/index.html':'html'})
            with self.assertRaises(ValueError):run(self.s.candidate,sha,{path:files[path]['sha256']})
        (self.s.candidate/path).write_text('changed')
        with self.assertRaises(ValueError):run(self.s.candidate,sha,{path:files[path]['sha256']})
