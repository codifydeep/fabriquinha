import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import prepare_c10_correction as prepare
from portable_browser_qa import validate

ROOT=Path(__file__).resolve().parents[1]


class GenerationPreparationTests(unittest.TestCase):
    def test_contract_protects_all_existing_tests_and_only_edits_client(self):
        template=json.loads((ROOT/'projects/descartavel2-search-1-ui.contract.json').read_text())
        tracked=template['files']+['tests/test_incremental_u3.py']
        contract,spec=prepare.derive(tracked,template)
        self.assertEqual(contract['editable_files'],['app/static/app.js',prepare.TEST])
        self.assertTrue(set(tracked)-{'app/static/app.js'}<=set(contract['protected_files']))
        self.assertEqual(spec['browser_qa']['scenario'],'feedback-board-search-generation-v1')
        self.assertIn('PHASE1 write ONLY',spec['description'])

    def test_existing_regression_cannot_be_overwritten(self):
        template=json.loads((ROOT/'projects/descartavel2-search-1-ui.contract.json').read_text())
        with self.assertRaises(ValueError):prepare.derive(template['files']+[prepare.TEST],template)

    def test_generation_browser_scenario_is_fixed(self):
        config={'scenario':'feedback-board-search-generation-v1','browser_image':'sha256:'+'a'*64}
        self.assertEqual(validate(config),config)

    def helper(self):
        tree=ast.parse((ROOT/'browser_feedback_acceptance.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observe_same_view_generation')
        ns={'json':json};exec(compile(ast.Module(body=[function],type_ignores=[]),'<fixed QA helper>','exec'),ns)
        return ns['observe_same_view_generation']

    def exercise(self,stale_paints):
        class Page:
            def __init__(self):self.rows=[];self.removed=False
            def route(self,pattern,fn):self.capture=fn
            def evaluate(self,script):
                if '__deliveryGenerationQa' not in script:return
                for index in range(2):
                    route=SimpleNamespace(request=SimpleNamespace(method='GET',url='http://fixture:8080/feedback'))
                    def fulfill(*,body,index=index,**kw):
                        if index==1 or stale_paints:self.rows=[v['title'] for v in json.loads(body)['items']]
                    route.fulfill=fulfill;self.capture(route)
            def wait_for_function(self,script):pass
            def locator(self,selector):return self
            def unroute(self,*args):self.removed=True
        class Expect:
            def __init__(self,page):self.page=page
            def to_have_text(self,value):
                if self.page.rows!=value:raise AssertionError('stale response painted')
        page=Page()
        try:self.helper()(page,Expect)
        finally:self.assertTrue(page.removed)

    def test_browser_driver_rejects_stale_repaint(self):
        with self.assertRaisesRegex(AssertionError,'stale response'):self.exercise(True)

    def test_browser_driver_accepts_guarded_response(self):self.exercise(False)
