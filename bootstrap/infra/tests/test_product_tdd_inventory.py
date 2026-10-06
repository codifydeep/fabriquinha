import json,unittest
from product_tdd_inventory import evaluate

def result(statuses):
    return dict(output=json.dumps(dict(testResults=[dict(name='/tmp/work/tests/a.test.ts',assertionResults=[dict(fullName=k,status=s,failureMessages=['AssertionError: expected behavior'] if s=='failed' else []) for k,s in statuses.items()])])),exit_code=int('failed' in statuses.values()))

class InventoryTests(unittest.TestCase):
    def test_missing_report_preserves_actual_infrastructure_error(self):
        from product_case_inventory import inventory
        with self.assertRaisesRegex(ValueError,'VALIDATION_CONTRACT_DRIFT package.json'):
            inventory(dict(exit_code=2,output='VALIDATION_CONTRACT_DRIFT package.json'))
    def setUp(self):
        self.card=dict(files={'tests/a.test.ts':'characterization'})
        self.base=dict(cases={'tests/a.test.ts::old':dict(status='passed',path='tests/a.test.ts')},failed_cases=[])
    def test_new_behavior_red_preserves_baseline(self):
        r=evaluate(self.card,self.base,result(dict(old='passed',new='failed')),'red',{})
        self.assertEqual(r['coverage']['preserved'],1)
    def test_unchanged_baseline_failure_is_not_accepted_red(self):
        with self.assertRaises(PermissionError):evaluate(self.card,self.base,result(dict(old='failed',new='failed')),'red',{})
    def test_missing_case_and_skipped_case_rejected(self):
        for statuses in (dict(new='failed'),dict(old='skipped',new='failed')):
            with self.assertRaises((PermissionError,ValueError)):evaluate(self.card,self.base,result(statuses),'red',{})
    def test_refactor_uses_same_characterization_not_artificial_red(self):
        self.card['tdd_mode']='refactor'
        evaluate(self.card,self.base,result(dict(old='passed')),'green',self.card['files'])
        with self.assertRaises(PermissionError):evaluate(self.card,self.base,result(dict(old='failed')),'red',self.card['files'])
        with self.assertRaises(PermissionError):evaluate(self.card,self.base,result(dict(old='passed')),'green',{'tests/a.test.ts':'weakened'})
    def test_registered_bugfix_can_use_existing_reproduction(self):
        self.card['tdd_mode']='bugfix';self.base['failed_cases']=['tests/a.test.ts::old']
        evaluate(self.card,self.base,result(dict(old='failed')),'red',{})
    def test_reviewed_maintenance_can_change_contract_case_but_not_others(self):
        evaluate(self.card,self.base,result(dict(old='failed')),'red',{},dict(observed_red_cases=['tests/a.test.ts::old']))
