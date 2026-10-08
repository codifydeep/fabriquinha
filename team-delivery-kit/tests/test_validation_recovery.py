import copy
import unittest
from broker.validation_recovery import eligible


class ValidationRecoveryEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.route=dict(author='author',issue_id='issue',contract_sha256='hash')
        self.data=dict(contract_sha256='hash',source_status='completed',error_type='DockerOperationTimeout',
                       error='Docker operation deadline')
        self.source=dict(id='task',agent_id='author',issue_id='issue',status='completed',created_at='1')
        self.runs=[self.source];self.snapshot=dict(status='complete');self.bindings=[dict(status='closed',mode='implementation')]
    def call(self):eligible(self.route,self.data,self.source,self.runs,self.snapshot,self.bindings)
    def test_exact_completed_infrastructure_case(self):self.call()
    def test_no_semantic_failure_missing_snapshot_or_active_execution_can_resume(self):
        for field,value in (('error_type','ValueError'),('validation_failure',{'category':'executed_test_failure'}),
                            ('evidence',{'green':True}),('contract_sha256','other')):
            original=copy.deepcopy(self.data);self.data[field]=value
            with self.assertRaises(ValueError):self.call()
            self.data=original
        self.runs.append(dict(id='review',status='running',agent_id='peer'))
        with self.assertRaises(ValueError):self.call()
        self.runs.pop();self.snapshot['status']='capturing'
        with self.assertRaises(ValueError):self.call()
    def test_latest_author_and_closed_implementation_binding_required(self):
        self.runs.append({**self.source,'id':'new','created_at':'2'})
        with self.assertRaises(ValueError):self.call()
        self.runs.pop();self.bindings[0]['mode']='review'
        with self.assertRaises(ValueError):self.call()
