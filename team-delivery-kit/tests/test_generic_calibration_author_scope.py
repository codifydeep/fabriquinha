import unittest
from broker import generic_calibration_gate as gate,native


class AuthorScopeTests(unittest.TestCase):
    def setUp(self):
        self.task=dict(id='task',agent_id='author',workspace_id='workspace',issue_id='issue',status='completed')
        self.binding=dict(task_id='task',agent_id='author',issue_id='issue',scope='workspace:author:implementation:issue')

    def test_completed_correction_retains_issue_workspace_not_task_workspace(self):
        gate.require_author_scope(self.binding,self.task)
        with self.assertRaises(ValueError):gate.require_author_scope({**self.binding,'scope':'workspace:author:implementation:task'},self.task)

    def test_chat_session_and_isolated_author_marker_follow_the_native_scope_contract(self):
        task={**self.task,'chat_session_id':'chat'}
        gate.require_author_scope({**self.binding,'scope':'workspace:author:implementation:chat'},task)
        task['handoff_note']='DELIVERY_SCOPE_AUTHOR_START '+'a'*64
        gate.require_author_scope({**self.binding,'scope':'workspace:author:implementation:task'},task)
        self.assertEqual(native.scope_source(task,'planning'),'task')

    def test_foreign_workspace_actor_task_issue_or_open_lease_cannot_be_rebound(self):
        for changes in ({'workspace_id':'other'},{'agent_id':'other'},{'id':'other'},
                        {'issue_id':'other'},{'status':'running'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                gate.require_author_scope(self.binding,{**self.task,**changes})
