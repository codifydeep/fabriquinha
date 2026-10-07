import tempfile,unittest
from pathlib import Path
from template_line_maintenance import read_proof,RUNTIME


class TemplateLineMaintenanceTests(unittest.TestCase):
    def test_runtime_is_compilable_and_retains_observation_only_uncertain_intents(self):
        compile(RUNTIME,'maintenance','exec')
        self.assertIn("if not info and first:",RUNTIME)
        self.assertIn("rec['stage']='start_intent';save()",RUNTIME)
        self.assertIn('observe_uncertain_start_no_repost',RUNTIME)
        self.assertIn('new=lane.arm(b,source,info',RUNTIME)
        self.assertNotIn('ensure_wakeup',RUNTIME)

    def test_one_exact_sanitized_proof_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'proof.log'
            path.write_text('noise\n{"schema":"expected","status":"passed"}\n')
            self.assertEqual(read_proof(path,'expected')['status'],'passed')
            with self.assertRaises(ValueError):read_proof(path,'other')
            path.write_text('{"schema":"expected"}\n{"schema":"expected"}\n')
            with self.assertRaises(ValueError):read_proof(path,'expected')
