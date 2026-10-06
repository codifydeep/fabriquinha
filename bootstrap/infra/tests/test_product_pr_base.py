import unittest
from unittest.mock import Mock,patch
from product_pr_base import refresh

class PRBaseTests(unittest.TestCase):
    def setUp(self):
        self.c=Mock();self.c.cfg={'attempt':'a','cards':{'t':{'author':'backend_data','base':'a'*40}}}
        self.c.source_files.return_value={'server/a.ts':'latest source'}
        self.pub=dict(pr=7,head='b'*40,release_base='a'*40,source_task='t')
        self.pr=dict(base=dict(ref='release/v0.1',sha='c'*40),head=dict(ref='codex/work',sha='b'*40,repo=dict(full_name='codifydeep/truco-online')),state='open',merged=False)
    def test_refresh_requires_fresh_delivery_and_preserves_old_branch(self):
        with patch('product_publication.approved_packet',return_value={}),patch('product_base_update.prepare',return_value='new') as prep,patch('product_autonomy.api',return_value=self.pr) as api:
            self.assertTrue(refresh(self.c,self.pub,self.pr))
        self.assertEqual(self.pub['state'],'SUPERSEDED');self.assertEqual(self.pub['replacement_task'],'new')
        self.assertEqual(prep.call_args.args[3]['files'],self.c.source_files.return_value)
        paths=[call.args[0] for call in api.call_args_list]
        self.assertFalse(any('git/refs' in p or p=='merges' for p in paths))
    def test_platform_wait_does_not_close_pr(self):
        with patch('product_publication.approved_packet',return_value={}),patch('product_base_update.prepare',return_value=None),patch('product_autonomy.api') as api:
            self.assertTrue(refresh(self.c,self.pub,self.pr));api.assert_not_called()
        self.assertNotIn('state',self.pub)
    def test_external_or_foreign_branch_refused(self):
        self.pr['head']['sha']='d'*40
        with self.assertRaises(PermissionError):refresh(self.c,self.pub,self.pr)
