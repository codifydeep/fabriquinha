import copy
import json
import unittest
from unittest.mock import Mock
import test_incremental_checkpoints as fixtures
from broker import incremental_provisioning as provision


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.IncrementalCheckpointTests();fixture.setUp()
        self.con=fixture.con;self.addCleanup(self.con.close)
        self.parent={'project_id':'project'}
        self.effects=Mock()
        self.issues={}
        def ensure(plan):
            if plan['title'] not in self.issues:
                self.issues[plan['title']]=dict(id='issue-'+str(len(self.issues)+1),identifier='EVAL-'+str(len(self.issues)+1))
            return self.issues[plan['title']]
        self.effects.ensure.side_effect=ensure

    def provision(self):return provision.ensure_issues(self.con,'source',self.parent,self.effects)

    def test_units_created_once_unassigned_with_exact_disjoint_scope_and_order(self):
        first=self.provision()
        self.assertEqual(len(first),2)
        self.assertEqual(self.provision(),first)
        self.assertEqual(self.effects.ensure.call_count,2)
        plans=[call.args[0] for call in self.effects.ensure.call_args_list]
        self.assertEqual([p['stage'] for p in plans],[1,2])
        self.assertIn('C01: First',plans[0]['description'])
        self.assertNotIn('C02: Second',plans[0]['description'])
        self.assertTrue(all('assignee_id' not in p for p in plans))

    def test_accepted_remote_creation_after_timeout_reuses_exact_intent(self):
        original=self.effects.ensure.side_effect
        count=0
        def ambiguous(plan):
            nonlocal count
            result=original(plan);count+=1
            if count==1:raise TimeoutError()
            return result
        self.effects.ensure.side_effect=ambiguous
        with self.assertRaises(TimeoutError):self.provision()
        result=self.provision()
        self.assertEqual(len(result),2);self.assertEqual(len(self.issues),2)
        self.assertEqual(self.effects.ensure.call_args_list[0].args[0],self.effects.ensure.call_args_list[1].args[0])

    def test_two_identical_failures_stop_and_preserve_incident(self):
        self.effects.ensure.side_effect=TimeoutError()
        for _ in range(2):
            with self.assertRaises(TimeoutError):self.provision()
        with self.assertRaises(ValueError):self.provision()
        self.assertEqual(self.effects.ensure.call_count,2)
        saved=json.loads(self.con.execute('SELECT state FROM incremental_provisioning').fetchone()[0])
        self.assertEqual(saved['stage'],'blocked');self.assertEqual(saved['owner'],'cto')

    def test_authorized_execution_cannot_be_reprovisioned(self):
        config,state=self.con.execute('SELECT config,state FROM incremental_checkpoints').fetchone()
        state=json.loads(state);state['execution_authorized']=True
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):self.provision()
        self.effects.ensure.assert_not_called()


class NativeIssueTests(unittest.TestCase):
    def setUp(self):
        self.api=provision.NativeIssues({'workspace_id':'workspace'})
        self.plan=dict(title='unit',description='exact',parent_issue_id='parent',project_id='project',stage=1,status='todo')
        self.issue=dict(self.plan,id='id',identifier='EVAL-1',assignee_id=None,workspace_id='workspace')

    def test_complete_pagination_recovers_existing_issue_without_post(self):
        self.api.request=Mock(side_effect=[{'issues':[{'id':'other','title':'other'}],'total':2},
                                          {'issues':[self.issue],'total':2}])
        self.assertEqual(self.api.ensure(self.plan),self.issue)
        self.assertEqual(self.api.request.call_count,2)
        self.assertTrue(all(len(c.args)==1 for c in self.api.request.call_args_list))

    def test_duplicate_or_changed_issue_cannot_be_adopted(self):
        for issues in ([self.issue,dict(self.issue,id='duplicate')],[dict(self.issue,description='changed')],
                       [dict(self.issue,assignee_id='author')]):
            self.api.request=Mock(return_value={'issues':issues,'total':len(issues)})
            with self.assertRaises(ValueError):self.api.ensure(self.plan)

    def test_incomplete_lookup_does_not_blindly_create_an_issue(self):
        self.api.request=Mock(return_value={'issues':[],'total':1})
        with self.assertRaises(ValueError):self.api.ensure(self.plan)
        self.api.request.assert_called_once()
