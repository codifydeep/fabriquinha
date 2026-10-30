"""A replan cannot silently omit authorized files or select a foreign plan."""
import sys,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.maintenance_replan import plan_scope,selection
from fabriquinha.effects import write_json

class MaintenanceReplan(TestCase):
    def test_scope_names_every_file_but_does_not_replace_semantic_review(self):
        paths=['tests/a.py','tests/b.py']
        for tasks in ([],[{'acceptance':'tests/a.py'}],[{'acceptance':' '.join(paths)}]*2):
            with self.assertRaises(ValueError):plan_scope({'tasks':tasks},paths)
        plan_scope({'tasks':[{'acceptance':'Only edit '+' '.join(paths)}]},paths)

    def test_selection_requires_exact_controller_receipt_and_native_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);state=dict(plan='t_12345678',authorization='auth',authority='scope',diagnosis='hold')
            write_json(folder/'maintenance-replan.json',state)
            payload={k:v for k,v in state.items() if k not in ('plan','authorization')}
            record=dict(binding={'release':'r'},payload=payload)
            task=SimpleNamespace(body=json.dumps(dict(maintenance_replan='auth',inputs={'approved_brief':'scope'})))
            r=SimpleNamespace(folder=lambda a:folder,binding=lambda a:{'release':'r'},store=SimpleNamespace(receipt=lambda *a,**kw:record))
            kb=SimpleNamespace(get_task=lambda *args:task)
            with patch('fabriquinha.maintenance_replan.native',return_value=(kb,None,None)):
                self.assertEqual(selection(r,None,None),state)
                task.body=json.dumps(dict(maintenance_replan='other',inputs={'approved_brief':'scope'}))
                with self.assertRaisesRegex(ValueError,'exact native'):selection(r,None,None)
                record['binding']={'release':'foreign'}
                with self.assertRaisesRegex(ValueError,'pointer drift'):selection(r,None,None)
