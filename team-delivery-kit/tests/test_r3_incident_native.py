import json
import unittest
from unittest.mock import Mock,patch
from broker.r3_incident_native import request,digest
from r3_incident_contract import planning_instruction


class R3IncidentNativeTests(unittest.TestCase):
    def setUp(self):
        self.settings={'agents':{'tl':'planning','cto':'planning'}}
        self.config=dict(evidence={'root_issue':'root','source_task':'source','facts':{'F01':'controller_handle_missing'},
            'execution_authorized':False,'release_homologated':False},techlead='tl',cto='cto')
        self.config['evidence_sha256']=digest(self.config['evidence'])
        self.state=dict(stage='observe_diagnose',issue_id='incident')
        self.item=dict(id='incident',parent_issue_id='root',title='R3 publication incident '+self.config['evidence_sha256'][:16],stage=3,status='todo')

    def invoke(self,operation,body):
        return request(operation,body,broker=Mock(),settings=self.settings)

    def test_native_wakeup_uses_exact_planning_actor_marker_and_no_generic_tools(self):
        with patch('broker.r3_incident_native.binding',return_value={'techlead':'tl','cto':'cto'}),\
             patch('broker.r3_incident_native.NativeIssues') as issues,\
             patch('broker.r3_incident_native.native.ensure_planning_start',return_value={'id':'wake'}) as wake:
            issues.return_value.request.return_value=self.item
            body=dict(config=self.config,state=self.state,note=planning_instruction(self.config,self.state),allow_create=True)
            self.assertEqual(self.invoke('wake',body),{'id':'wake'})
            self.assertEqual(wake.call_args.args[2],'tl')
            self.assertTrue(wake.call_args.kwargs['allow_create'])
            body['allow_create']=False;self.invoke('wake',body)
            self.assertFalse(wake.call_args.kwargs['allow_create'])
            body['note']+='\nrun a shell'
            with self.assertRaises(ValueError):self.invoke('wake',body)
            self.assertEqual(wake.call_count,2)

    def test_wrong_parent_or_obsolete_actor_never_wakes(self):
        with patch('broker.r3_incident_native.binding',return_value={'techlead':'tl','cto':'cto'}),\
             patch('broker.r3_incident_native.NativeIssues') as issues,\
             patch('broker.r3_incident_native.native.ensure_planning_start') as wake:
            issues.return_value.request.return_value={**self.item,'parent_issue_id':'wrong'}
            with self.assertRaises(ValueError):
                self.invoke('wake',dict(config=self.config,state=self.state,note=planning_instruction(self.config,self.state),allow_create=True))
            wrong={**self.config,'techlead':'another'}
            with self.assertRaises(ValueError):self.invoke('runs',dict(config=wrong,state=self.state))
            wake.assert_not_called()

    def test_restart_merge_shell_and_extra_parameters_are_not_adapter_operations(self):
        for operation,body in (('restart',{}),('merge',{}),('shell',{'command':'echo nope'}),('remaining',{'raise_cap':True})):
            with self.assertRaises(ValueError):self.invoke(operation,body)

    def test_foreign_task_is_never_exported_to_incident_controller(self):
        with patch('broker.r3_incident_native.binding',return_value={'techlead':'tl','cto':'cto'}),\
             patch('broker.r3_incident_native.NativeIssues') as issues,\
             patch('broker.r3_incident_native.native.task_record') as task:
            issues.return_value.request.return_value=self.item
            state={**self.state,'stage':'awaiting_diagnose','task_id':'selected','wakeup_id':'wake'}
            with self.assertRaises(ValueError):self.invoke('task',dict(config=self.config,state=state,task='foreign'))
            task.assert_not_called()
            task.return_value=dict(id='selected',issue_id='foreign',agent_id='tl',wakeup_id='wake')
            with self.assertRaises(ValueError):self.invoke('task',dict(config=self.config,state=state,task='selected'))
