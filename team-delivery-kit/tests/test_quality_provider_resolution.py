"""Synthetic payment-resolution facts never establish provider credit or approval."""
import copy
import time
import unittest
import quality_provider_resolution as contract


def facts():
    operation='a0000000-0000-4000-8000-000000000001'
    request='a0000000-0000-4000-8000-000000000002'
    event=dict(event='model_proxy_request',status=402,category='upstream_response',call_number=17,
        route='/api/v1/chat/completions',execution_id=request,started_at=100.,duration_seconds=2.,
        response_deadline_seconds=120)
    pause=dict(category='upstream_payment_required',upstream_status=402,call_number=17)
    resolution=dict(operation='operator_provider_access_resolution_v1',operation_id=operation,pause=pause,
        calls_before=17,calls_after=17,account_balance_positive=True,key_remaining_positive=True,
        delivery_approval=False,resolved_at=103.)
    return dict(operation='observed_review_payment_resolution_v1',namespace='delivery-kit-test',
        maintenance_operation=operation,request_id=request,proxy_container='1'*64,proxy_image='sha256:'+'2'*64,
        resolver_sha256=contract.source_sha256(),proxy_source_sha256='3'*64,event=event,resolution=resolution,
        counter=dict(calls=17,sha256='4'*64),max_calls=10000,pause_absent=True,
        operator_confirmed=True,model_calls=0,delivery_approval=False)


class QualityProviderResolutionTests(unittest.TestCase):
    def call(self,value=None,now=104.):
        value=facts() if value is None else value
        return contract.validate(value,'delivery-kit-test',facts()['maintenance_operation'],
            facts()['request_id'],proxy_source='3'*64,now=now)

    def test_exact_payment_fact_is_non_authorizing_and_immutable(self):
        value=facts();before=copy.deepcopy(value);result=self.call(value)
        self.assertEqual(value,before);self.assertEqual(len(result),64)
        self.assertFalse(value['delivery_approval']);self.assertEqual(value['model_calls'],0)

    def test_operation_and_timestamp_changes_do_not_renew_the_same_condition(self):
        value=facts();identity='a0000000-0000-4000-8000-000000000003'
        value['maintenance_operation']=identity;value['resolution']['operation_id']=identity
        self.assertEqual(contract.validate(value,'delivery-kit-test',identity,facts()['request_id'],
            proxy_source='3'*64,now=104.),self.call())

    def test_no_inferred_operator_confirmation_credit_or_counter_reset(self):
        for changes in (dict(operator_confirmed=False),dict(operator_confirmed=1),dict(pause_absent=False),
                dict(model_calls=1),dict(model_calls=False),dict(delivery_approval=True),dict(max_calls=17),
                dict(resolver_sha256='0'*64),dict(proxy_source_sha256='0'*64),dict(extra=True)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.call({**facts(),**changes})
        for key,value in (('account_balance_positive',False),('key_remaining_positive',False),
                ('calls_after',18),('calls_before',True),('resolved_at',float('inf')),('resolved_at',90.)):
            changed=facts();changed['resolution'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.call(changed)

    def test_only_the_original_upstream_payment_event_can_qualify(self):
        for key,value in (('status',403),('status',True),('category','upstream_payment_paused'),
                ('call_number',18),('call_number',True),('execution_id','other'),
                ('started_at',float('nan')),('duration_seconds',121),('response_deadline_seconds',90)):
            changed=facts();changed['event'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.call(changed)
        changed=facts();changed['resolution']['pause']['call_number']=16
        with self.assertRaises(ValueError):self.call(changed)

    def test_foreign_or_expired_resolution_does_not_become_a_retry_permission(self):
        for key,value in (('namespace','delivery-kit-other'),('request_id','a0000000-0000-4000-8000-000000000003'),
                ('proxy_container','bad'),('proxy_image','tag:latest')):
            with self.subTest(key=key),self.assertRaises(ValueError):self.call({**facts(),key:value})
        with self.assertRaises(ValueError):self.call(now=1004.)


if __name__=='__main__':unittest.main()
