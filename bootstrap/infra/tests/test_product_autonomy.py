import json,unittest
from unittest.mock import Mock,patch
from product_autonomy import Coordinator
from product_workspace import digest

class AutonomyGateTests(unittest.TestCase):
    def setUp(self):
        self.c=Coordinator.__new__(Coordinator);self.c.private=Mock();self.c.native=Mock();self.c.put=Mock();self.c.notice=Mock();self.c.finish_merge=Mock()
        self.c.cfg=dict(cards={'review':dict(author='techlead',reviewer='cto')})
        self.pub=dict(pr=23,head='a'*40,author='techlead',source_task='source')
        self.v=dict(task='review',run=4,decision='approve',head='a'*40,base='b'*40,author='techlead',reviewer='cto',reason='Independent exact review')
        self.c.private.execute.return_value.fetchone.return_value=(json.dumps(self.v),'DELIVERED')
        self.c.native.execute.return_value.fetchone.return_value=('completed','product-pr-verdict:'+digest(self.v)+'\n'+self.v['reason'])
        self.pr=dict(head={'sha':'a'*40,'repo':{'full_name':'codifydeep/truco-online'}},base={'sha':'b'*40,'ref':'release/v0.1'})
        self.c.ci=Mock(return_value=dict(id=123,conclusion='success'))
    def test_requested_changes_never_merge(self):
        self.v['decision']='request_changes';self.c.private.execute.return_value.fetchone.return_value=(json.dumps(self.v),'DELIVERED')
        self.c.native.execute.return_value.fetchone.return_value=('changes_requested','product-pr-verdict:'+digest(self.v)+'\n'+self.v['reason'])
        self.c.recovery=Mock()
        with patch('product_autonomy.api') as api:self.c.integrate(self.pub,self.pr,dict(id=123),'review');api.assert_not_called()
        self.c.recovery.assert_called_once_with(self.pub,self.pr,dict(kind='review_changes',review_task='review',reason=self.v['reason']))
    def test_stale_base_denied(self):
        with patch('product_autonomy.api') as api:
            with self.assertRaises(PermissionError):self.c.integrate(self.pub,dict(self.pr,base={'sha':'c'*40}),dict(id=123),'review')
            api.assert_not_called()
    def test_fresh_failed_ci_denied(self):
        self.c.ci.return_value=dict(id=123,conclusion='failure')
        with patch('product_autonomy.api',return_value=self.pr) as api:
            with self.assertRaises(PermissionError):self.c.integrate(self.pub,self.pr,dict(id=123),'review')
            self.assertEqual(api.call_count,1)
    def test_pending_checks_denied(self):
        with patch('product_autonomy.api',side_effect=[self.pr,{'check_runs':[{'status':'in_progress','conclusion':None}]}]) as api:
            with self.assertRaises(PermissionError):self.c.integrate(self.pub,self.pr,dict(id=123),'review')
            self.assertTrue(all(len(c.args)==1 for c in api.call_args_list))
    def test_only_exact_head_normal_merge(self):
        with patch('product_autonomy.api',side_effect=[self.pr,{'check_runs':[{'status':'completed','conclusion':'success'}]}, {}, {'merged':True}, self.pr]) as api:
            self.c.integrate(self.pub,self.pr,dict(id=123),'review')
            merge=api.call_args_list[3];self.assertEqual(merge.args,('pulls/23/merge','PUT',dict(sha='a'*40,merge_method='merge')))
            self.c.put.assert_called_once();self.c.finish_merge.assert_called_once()
    def test_merged_without_our_intent_denied(self):
        self.c.get=Mock(return_value=None)
        with self.assertRaises(PermissionError):Coordinator.finish_merge(self.c,self.pub,{'head':{'sha':'a'*40}})
