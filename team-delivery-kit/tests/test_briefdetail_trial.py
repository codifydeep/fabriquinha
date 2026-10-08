import copy
import json
from pathlib import Path
import unittest
from prepare_briefdetail_trial import derive,PREFIX
from planning_intake import brief_body

ROOT=Path(__file__).parents[1]


class DetailBriefTests(unittest.TestCase):
    def test_fresh_brief_import_is_bounded_and_business_acceptance_is_explicit(self):
        body=brief_body((ROOT/'projects'/(PREFIX+'.brief.md')).read_text())
        for text in ('/feedback/<id>','stale responses','literal title','Keyboard','full regressions'):
            self.assertIn(text,body)
        self.assertLessEqual(len(body),2200)

    def test_current_baseline_tests_stay_protected_and_product_code_is_not_generated(self):
        folder=ROOT/'projects'
        template=json.loads((folder/'descartavel2-briefdemo-2-api.qa.contract.json').read_text())
        tracked=set(template['files'])-{'tests/test_demo_mode_api_template.py'}
        tracked|={'tests/test_actual_demo_api.py','test_actual_demo_ui.py'}
        runs=[json.loads((folder/('descartavel2-briefdemo-2-'+k+'.qa.run.json')).read_text()) for k in ('api','ui')]
        original=copy.deepcopy(template)
        outputs=derive(tracked,template,runs)
        for kind in ('api','ui'):
            self.assertEqual(outputs[PREFIX+'-'+kind+'.qa.run.json']['browser_qa']['scenario'],
                             'feedback-board-detail-'+kind+'-v1')
        self.assertEqual(template,original)
        for kind in ('api','ui'):
            contract=outputs[PREFIX+'-'+kind+'.qa.contract.json']
            self.assertTrue(tracked<=set(contract['files']))
            for name in tracked:
                if 'test' in name and name.endswith('.py'):self.assertIn(name,contract['protected_files'])
        self.assertNotIn('cards',outputs[PREFIX+'.delivery.json'])
        self.assertEqual(outputs[PREFIX+'.planning.json']['base_sha'],'90fac1054a263be42ec2545b3f82f0785f9de87d')
