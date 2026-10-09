import copy
import unittest
from broker.provider_access_recovery import qualify, ERROR


class ProviderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(source_task='source',stage='awaiting_acceptance',owner='cto')
        self.route=dict(author='author',cto='cto',contract_sha256='hash')
        self.data=dict(contract_sha256='hash',source_status='failed',
            source_failure_reason='agent_error.provider_server_error',error='recipient_execution_failed',
            target='cto',dispatch_stage='diagnose_cto',wakeup_id='wake')
        self.runs=[dict(id='source',agent_id='author',status='failed',error=ERROR),
            dict(id='recipient',agent_id='cto',status='failed',error=ERROR,wakeup_id='wake',
                failure_reason='agent_error.provider_server_error')]
        self.bindings=[dict(status='closed',mode='implementation')]
        self.resolution=dict(operation='operator_provider_access_resolution_v1',
            operation_id='584b952d-f4c2-4e62-a8f5-6997560fce3d',calls_before=5948,calls_after=5948,
            account_balance_positive=True,key_remaining_positive=True,delivery_approval=False,
            pause=dict(upstream_status=403,call_number=5948))
    def call(self):
        return qualify(self.row,self.route,self.data,self.runs,self.bindings,self.resolution)
    def test_qualified_replay_is_only_cto_diagnosis(self):
        self.assertEqual(self.call(),'recipient')
    def test_pause_and_counter_and_operator_authority_cannot_be_inferred(self):
        for key,value in [('account_balance_positive',False),('key_remaining_positive',False),
                ('calls_after',0),('delivery_approval',True),('calls_before',True)]:
            old=copy.deepcopy(self.resolution);self.resolution[key]=value
            with self.assertRaises(ValueError):self.call()
            self.resolution=old
    def test_no_active_stale_or_approved_work(self):
        for key,value in [('validation_failure',{'category':'executed_test_failure'}),
                ('contract_sha256','other'),('dispatch_stage','correct_author'),('evidence',{'green':True})]:
            old=copy.deepcopy(self.data);self.data[key]=value
            with self.assertRaises(ValueError):self.call()
            self.data=old
        self.runs.append(dict(id='new',status='running',agent_id='peer'))
        with self.assertRaises(ValueError):self.call()
    def test_closed_author_and_single_failed_cto_required(self):
        self.bindings[0]['mode']='review'
        with self.assertRaises(ValueError):self.call()
        self.bindings[0]['mode']='implementation';self.runs[1]['error']='different failure'
        with self.assertRaises(ValueError):self.call()
    def test_new_author_and_duplicate_recipient_forbid_replay(self):
        self.runs.append(dict(self.runs[0],id='new',created_at='2099'))
        with self.assertRaises(ValueError):self.call()
        self.runs.pop();self.runs.append(dict(self.runs[1],id='duplicate'))
        with self.assertRaises(ValueError):self.call()
