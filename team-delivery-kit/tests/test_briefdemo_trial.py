import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from prepare_briefdemo_trial import derive, PREFIX
from portable_browser_qa import validate

ROOT=Path(__file__).parents[1]


class FreshDemoBriefTests(unittest.TestCase):
    def test_fresh_brief_passes_real_import_contract_before_service_registration(self):
        from planning_intake import brief_body
        body=brief_body((ROOT/'projects'/ (PREFIX+'.brief.md')).read_text())
        self.assertIn('/service-mode',body)
        self.assertLessEqual(len(body),2200)
    def test_templates_preserve_entire_baseline_and_defer_worker_scopes_to_agents(self):
        folder=ROOT/'projects'
        template=json.loads((folder/'descartavel2-briefstatus-1-api.qa.contract.json').read_text())
        runs=[json.loads((folder/('descartavel2-briefstatus-1-'+k+'.qa.run.json')).read_text()) for k in ('api','ui')]
        tracked=sorted((set(template['files'])-{'tests/test_service_status_api_template.py'})|
                       {'test_service_status_indicator.py','test_real_service_status_api.py'})
        original=copy.deepcopy(template)
        out=derive(tracked,template,runs)
        for k in ('api','ui'):
            c=out[PREFIX+'-'+k+'.qa.contract.json']
            self.assertTrue(set(tracked)<=set(c['files']))
            for p in tracked:
                if p.endswith('.py') and 'test' in p:self.assertIn(p,c['protected_files'])
            self.assertEqual(c['qa_cases'][:len(template['qa_cases'])],template['qa_cases'])
        self.assertEqual(out[PREFIX+'.delivery.json']['minimum_calls'],256)
        self.assertNotIn('cards',out[PREFIX+'.delivery.json'])
        self.assertEqual(template,original)
        with self.assertRaises(ValueError):derive([p for p in tracked if p!='test_service_status_indicator.py'],template,runs)

    def test_demo_api_qa_rejects_missing_routes_and_weakened_json(self):
        tree=ast.parse((ROOT/'browser_feedback_acceptance.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observe_demo_mode_api')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'fixed-demo-qa','exec'),namespace)
        paths=[]
        for status,body,ctype,passes in [(200,{'mode':'demo'},'application/json',True),
            (404,{},'application/json',False),(200,{'mode':'demo','extra':True},'application/json',False),
            (200,{'mode':'other'},'application/json',False),(200,{'mode':'demo'},'text/html',False)]:
            response=SimpleNamespace(status=status,json=lambda:body,headers={'content-type':ctype})
            context=SimpleNamespace(request=SimpleNamespace(get=lambda path:paths.append(path) or response))
            if passes:namespace[node.name](context)
            else:
                with self.assertRaises(AssertionError):namespace[node.name](context)
        self.assertEqual(paths[:2],['http://fixture:8080/service-mode','http://fixture:8080/service-mode?probe=1'])
        for k in ('api','ui'):
            validate(dict(scenario='feedback-board-demo-mode-'+k+'-v1',browser_image='sha256:'+'a'*64))
