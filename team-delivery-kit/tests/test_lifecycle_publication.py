import copy
import unittest
from unittest.mock import Mock
from broker import lifecycle_publication as publication


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.issue=dict(id='maintenance',parent_issue_id='parent',assignee_id=None,
                        status='todo',description='contract')
        self.parent=dict(id='parent',assignee_id=None)
        self.fx=Mock();self.fx.get.side_effect=lambda key:copy.deepcopy(self.issue if key=='maintenance' else self.parent)
        self.fx.wakeups.return_value=[]
        def put(key,body):self.issue.update(body)
        self.fx.put.side_effect=put
        self.intent=dict(issue_id='maintenance',parent_id='parent',original_description='contract',
                         receipt_sha256='a'*64,root='root',original_issue_id='original')

    def test_publish_only_maintenance_and_reentry_never_writes_twice(self):
        result=publication.publish(self.intent,self.fx)
        self.assertEqual(result['stage'],'published');self.assertEqual(self.issue['status'],'done')
        self.fx.put.assert_called_once()
        body=self.fx.put.call_args.args[1]
        self.assertIs(body['suppress_run'],True)
        self.assertIn('NOT product delivery',body['description'])
        publication.publish(self.intent,self.fx);self.fx.put.assert_called_once()

    def test_parent_assignment_or_active_wakeup_prevents_any_write(self):
        self.parent['assignee_id']='agent'
        with self.assertRaises(ValueError):publication.publish(self.intent,self.fx)
        self.fx.put.assert_not_called();self.parent['assignee_id']=None
        self.fx.wakeups.return_value=[{'enabled':True}]
        with self.assertRaises(ValueError):publication.publish(self.intent,self.fx)
        self.fx.put.assert_not_called()

    def test_foreign_parent_or_description_cannot_be_overwritten(self):
        for key,value in [('parent_issue_id','other'),('description','changed'),('assignee_id','agent')]:
            original=self.issue[key];self.issue[key]=value
            with self.assertRaises(ValueError):publication.publish(self.intent,self.fx)
            self.issue[key]=original
        self.fx.put.assert_not_called()

    def test_lost_write_acknowledgment_is_reconciled_from_exact_native_state(self):
        def uncertain(key,body):
            self.issue.update(body)
            self.fx.wakeups.return_value=[{'enabled':True,'system_rule':'child_done'}]
            raise TimeoutError('lost acknowledgement')
        self.fx.put.side_effect=uncertain
        with self.assertRaises(TimeoutError):publication.publish(self.intent,self.fx)
        self.assertEqual(publication.publish(self.intent,self.fx)['stage'],'published')
        self.fx.put.assert_called_once()
