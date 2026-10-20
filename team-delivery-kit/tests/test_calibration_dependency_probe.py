import unittest
from calibration_dependency_probe import discover,read_contract_experiment


class DependencyProbeTests(unittest.TestCase):
    def test_static_fixture_paths_are_resolved_without_executing_the_module(self):
        raw=b'''from pathlib import Path
raise RuntimeError("must never execute")
ROOT = Path(__file__).resolve().parents[1]
RATIO = 3 / 2
PAGE = ROOT / "app/static/index.html"
SCRIPT = ROOT / "app" / "static" / "app.js"
'''
        files={p:{'sha256':'a'*64} for p in ('app/static/index.html','app/static/app.js','tests/test_new.py')}
        found=discover(raw,'tests/test_new.py',files)
        self.assertEqual({r['attribute']:r['path'] for r in found},
            {'PAGE':'app/static/index.html','SCRIPT':'app/static/app.js'})
    def test_dynamic_paths_or_escape_are_unsupported_not_guessed(self):
        for expression in ('Path("/secret")','Path(__file__).resolve().parents[9]',
                'Path(__file__).parent / "../secret"','Path(__file__).parent / get_name()'):
            with self.subTest(expression=expression),self.assertRaises(ValueError):
                discover(('SOURCE = '+expression).encode(),'tests/new.py',{})
    def test_unknown_paths_are_not_admitted_as_product_evidence(self):
        raw=b'ROOT=Path(__file__).resolve().parents[1]\nFILE=ROOT/"missing.js"\n'
        with self.assertRaises(ValueError):discover(raw,'tests/new.py',{'tests/new.py':{'sha256':'a'*64}})
    def test_mandatory_dependencies_force_actual_pagination_before_producer_choice(self):
        self.assertTrue(all(read_contract_experiment().values()))
