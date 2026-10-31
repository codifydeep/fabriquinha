"""Preflight the same manifests used by the two-release Docker qualifier."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_release import fixture_coverage
from fabriquinha.browser import acceptance_manifest


class ReleaseFixtureCoverage(unittest.TestCase):
    def test_second_release_inherits_regression_without_duplicate_declaration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            baseline={}
            for package,criterion in [('greet','GREET'),('farewell','BYE'),('thanks','THANK')]:
                (root/('acceptance_'+package+'.py')).write_text(
                    'class Browser(AcceptanceTest):\n def test_behavior(self): pass\n')
                (root/('acceptance.'+package+'.json')).write_text(json.dumps(fixture_coverage(package,criterion)))
                manifest=acceptance_manifest(root)
                if package=='farewell':baseline={p:p.read_bytes() for p in root.iterdir()}
            self.assertEqual(set(manifest['criteria']),{'GREET','BYE','THANK','NAMED','REGRESSION'})
            self.assertEqual(len(manifest['criteria']['NAMED']['cases']),3)
            self.assertEqual(manifest['criteria']['REGRESSION'],{'cases':[],'gates':['regression']})
            self.assertTrue(all(path.read_bytes()==content for path,content in baseline.items()))
