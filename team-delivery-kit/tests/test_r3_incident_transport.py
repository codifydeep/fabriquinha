import copy
import unittest
from r3_incident_transport import qualify_report, qualify_reason_report, ERROR_SHA


class R3IncidentTransportTests(unittest.TestCase):
    def test_reason_recovery_requires_two_exact_persisted_nonaccepted_length_failures(self):
        report=self.report()
        rejected=dict(operation='rejected_typed_decision_adapter_v1',category='typed_schema_maxLength',
                      delivery_approval=False,worker_tool_executed=False,
                      response_shape=dict(parsed=True,terminal=True,submissions=1,expected_tool=True,
                                          arguments_json_valid=True,arguments_schema_valid=False))
        for row in report['failures']:row['rejections']=[copy.deepcopy(rejected)]
        qualify_reason_report(report,['tl','cto'])
        for key,value in [('category','typed_wrong_tool_name'),('delivery_approval',True),('worker_tool_executed',True)]:
            changed=copy.deepcopy(report);changed['failures'][0]['rejections'][0][key]=value
            with self.assertRaises(ValueError):qualify_reason_report(changed,['tl','cto'])
        changed=copy.deepcopy(report);changed['failures'][0]['rejections'][0]['response_shape']['arguments_schema_valid']=True
        with self.assertRaises(ValueError):qualify_reason_report(changed,['tl','cto'])

    def report(self):
        rows=[]
        for task,execution in [('tl','exec-tl'),('cto','exec-cto')]:
            rejection=dict(execution_id=execution,stage='contract',origin={'module':'decision_schema'},
                           error_sha256=ERROR_SHA,retry_authorized=False,delivery_approval=False)
            rows.append(dict(task=task,execution=execution,
                receipt=dict(method='session/prompt',code=-32603,approval=False),
                rejections=[rejection]))
        return dict(active=0,failures=rows)

    def test_only_two_exact_local_prepaid_failures_qualify(self):
        qualify_report(self.report(),['tl','cto'])

    def test_other_failures_active_workers_and_paid_calls_remain_blocked(self):
        for change in ('active','missing','paid','wrong_error','authority','identity','upstream','duplicate'):
            report=copy.deepcopy(self.report());row=report['failures'][0];event=row['rejections'][0]
            if change=='active':report['active']=1
            if change=='missing':report['failures'].pop()
            if change=='paid':event['stage']='upstream'
            if change=='wrong_error':event['error_sha256']='b'*64
            if change=='authority':event['retry_authorized']=True
            if change=='identity':row['task']='other'
            if change=='upstream':row['receipt']['code']=500
            if change=='duplicate':row['rejections'].append(copy.deepcopy(event))
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_report(report,['tl','cto'])
