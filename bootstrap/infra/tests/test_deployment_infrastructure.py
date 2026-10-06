import json,sqlite3,unittest
from product_deployment_jobs import schema,infrastructure_failure,request
from product_deployment import ADAPTER_VERSION
from product_workspace import digest
from unittest.mock import patch

class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);schema(self.db)
        self.p=dict(task='original',specification={})
    def test_fixed_failure_stays_on_original_task(self):
        self.db.execute('INSERT INTO deployment_jobs VALUES(?,?,?,NULL,?)',('old',json.dumps(dict(proposal=self.p)),'FAILED','unknown flag: --timeout'))
        self.assertEqual(infrastructure_failure(self.db,'original')['owner'],'devops')
        self.assertIsNone(infrastructure_failure(self.db,'other'))
    def test_same_adapter_cannot_retry_failure_as_new_review(self):
        self.db.execute('INSERT INTO deployment_jobs VALUES(?,?,?,NULL,?)',('old',json.dumps(dict(proposal=self.p,adapter_version=ADAPTER_VERSION)),'FAILED','unknown flag: x'))
        with patch('product_deployment.validate'),self.assertRaises(PermissionError):request(self.db,dict(run=2),self.p,{})
    def test_repaired_adapter_keeps_old_failed_receipt(self):
        self.db.execute('INSERT INTO deployment_jobs VALUES(?,?,?,NULL,?)',('old',json.dumps(dict(proposal=self.p,adapter_version='older')),'FAILED','unknown flag: x'))
        with patch('product_deployment.validate'):
            a=request(self.db,dict(run=2),self.p,{})
            b=request(self.db,dict(run=2),self.p,{})
        self.assertEqual(a['job'],b['job'])
        self.assertEqual(self.db.execute('select count(*) from deployment_jobs').fetchone()[0],2)
        self.assertEqual(self.db.execute('select state from deployment_jobs where id=?',('old',)).fetchone()[0],'FAILED')
