import copy
import unittest
from unittest.mock import patch
from r3_review_json_recovery import qualify,recover


class ReviewJsonRecoveryTests(unittest.TestCase):
    def report(self):
        return dict(active=0,failures=[dict(receipt=dict(method='session/prompt',code=-32603,approval=False),
            rejections=[dict(operation='rejected_typed_decision_adapter_v1',category='typed_arguments_invalid',
                delivery_approval=False,worker_tool_executed=False,response_shape=dict(parsed=True,terminal=True,
                submissions=1,expected_tool=True,arguments_json_valid=False,content_shape='empty'))])])

    def test_exact_nonaccepted_malformed_review_qualifies(self):qualify(self.report())

    def test_other_failure_or_valid_arguments_cannot_reopen_review(self):
        for change in ('active','multiple','accepted','valid','wrong_tool','length','prose'):
            report=copy.deepcopy(self.report());rejected=report['failures'][0]['rejections'][0]
            if change=='active':report['active']=1
            if change=='multiple':report['failures'].append(copy.deepcopy(report['failures'][0]))
            if change=='accepted':rejected['delivery_approval']=True
            if change=='valid':rejected['response_shape']['arguments_json_valid']=True
            if change=='wrong_tool':rejected['response_shape']['expected_tool']=False
            if change=='length':rejected['category']='typed_schema_maxLength'
            if change=='prose':rejected['response_shape']['content_shape']='nonempty'
            with self.subTest(change=change),self.assertRaises(ValueError):qualify(report)

    def test_running_unproposed_or_already_recovered_reviews_are_never_repeated(self):
        base=dict(stage='blocked',category='invalid_incident_submission',proposal={'decision':'x'},diagnosis_task='cto')
        for state in ({**base,'stage':'awaiting_review'}, {**base,'proposal':None},
                      {**base,'review_transport_recovery_sha256':'a'*64}):
            with patch('r3_review_json_recovery.read') as read:
                self.assertIsNone(recover('/unused',state));read.assert_not_called()
