import copy
import unittest
from memory_format_recovery import qualify

class MemoryFormatRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.state={'stage':'blocked','category':'native_curator_failed','issue_id':'issue','delivery_approval':False}
        self.runs=[{'id':'task','status':'failed','agent_id':'reviewer'}]
        self.binding={'task_id':'task','agent_id':'reviewer','issue_id':'issue','mode':'planning',
            'lease_status':'closed','scope':'x:planning:y','request_id':'request'}
        self.event={'event':'model_proxy_request','execution_id':'request','status':502,
            'category':'structured_decision_response_invalid','structured_rejection_category':'schema_violation',
            'structured_format':'json_schema','strict_schema':True,'tool_count':0,'finish_reason':'stop',
            'call_number':12,'structured_rejection_diagnostic':{'version':'structured-constraint-v1',
                'constraints':['maxLength'],'upstream_sha256':'a'*64}}
    def call(self):return qualify(self.state,self.runs,self.binding,[self.event],'reviewer')
    def test_exact_failure_authorizes_only_one_changed_review_not_approval(self):
        value=self.call();self.assertEqual(value['stage'],'format_recovery_intent')
        self.assertEqual(value['format_recovery']['prior_failure'],self.state)
        self.assertNotIn('issue_id',value);self.assertFalse(value['delivery_approval'])
        self.assertIsNone(qualify(value,self.runs,self.binding,[self.event],'reviewer'))
    def test_other_constraint_active_lease_or_execution_cannot_retry(self):
        for field,value in [('lease_status','running'),('mode','implementation'),('issue_id','other')]:
            original=self.binding[field];self.binding[field]=value
            self.assertIsNone(self.call());self.binding[field]=original
        self.event['structured_rejection_diagnostic']['constraints']=['required']
        self.assertIsNone(self.call())
    def test_duplicate_events_and_missing_evidence_are_not_permission(self):
        self.assertIsNone(qualify(self.state,self.runs,self.binding,[self.event,self.event],'reviewer'))
        self.assertIsNone(qualify(self.state,self.runs,self.binding,[],'reviewer'))
