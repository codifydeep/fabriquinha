import ast
from pathlib import Path
import unittest


class BrowserRuntimeProbeTests(unittest.TestCase):
    def helper(self):
        source=Path(__file__).resolve().parents[1]/'browser_runtime_probe.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='renamed_variant')
        ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        return ns['renamed_variant']

    def test_intervention_changes_only_three_bound_references(self):
        original="var status = node; status.textContent = ''; status.classList.toggle('error');"
        variant=self.helper()(original)
        self.assertEqual(variant,"var formStatus = node; formStatus.textContent = ''; formStatus.classList.toggle('error');")
        self.assertEqual(original,"var status = node; status.textContent = ''; status.classList.toggle('error');")

    def test_missing_or_duplicate_binding_is_not_silently_repaired(self):
        for code in ('var status = node;',
                     "var status = node; var status = other; status.textContent = ''; status.classList.toggle('error');"):
            with self.assertRaises(ValueError):self.helper()(code)
