import unittest
from unittest.mock import patch
import integrate_u3_predecessors as gate


class ProtectedPredecessorIntegrationTests(unittest.TestCase):
    def test_enforced_strict_ci_required(self):
        good=dict(required_status_checks=dict(strict=True,contexts=['ci']),enforce_admins=dict(enabled=True))
        gate.protection_ok(good)
        for changed in (dict(good,enforce_admins=dict(enabled=False)),
                        dict(good,required_status_checks=dict(strict=False,contexts=['ci'])),
                        dict(good,required_status_checks=dict(strict=True,contexts=['other']))):
            with self.assertRaises(ValueError):gate.protection_ok(changed)

    def test_ci_bound_to_exact_sha_and_not_textual_success(self):
        check=dict(name='ci',head_sha='a'*40,status='completed',conclusion='success',id=1,html_url='https://example.invalid/ci')
        self.assertEqual(gate.exact_ci(dict(check_runs=[check]),'a'*40)['check_run_id'],1)
        for bad in (dict(check,head_sha='b'*40),dict(check,conclusion='failure')):
            with self.assertRaises(ValueError):gate.exact_ci(dict(check_runs=[bad]),'a'*40)
        with self.assertRaises(ValueError):gate.exact_ci(dict(check_runs=[check,check]),'a'*40)
        with self.assertRaises(gate.CIWaiting):gate.exact_ci(dict(check_runs=[]),'a'*40)

    def test_same_repository_head_and_base_required(self):
        pub=dict(pr_number=35,head_sha='a'*40,base_sha='b'*40)
        repo=dict(full_name=gate.common.REPOSITORY)
        pr=dict(number=35,head=dict(sha='a'*40,ref=gate.predecessor.BRANCH,repo=repo),
                base=dict(sha='b'*40,ref='main',repo=repo))
        gate.verify_pr(pr,pub)
        with self.assertRaises(ValueError):gate.verify_pr(dict(pr,head=dict(pr['head'],sha='e'*40)),pub)
        with self.assertRaises(ValueError):gate.verify_pr(dict(pr,base=dict(pr['base'],sha='e'*40)),pub)
        with self.assertRaises(ValueError):gate.verify_pr(dict(pr,head=dict(pr['head'],repo=dict(full_name='fork/repo'))),pub)

    def test_merged_tree_and_parent_are_rechecked(self):
        with patch.object(gate.common,'git',side_effect=[b'base\n',b'tree\n']),\
                patch.object(gate.common,'tracked',side_effect=[{'file':('100644','blob')},{'file':('100644','blob')}]):
            self.assertEqual(gate.verify_merged(None,'base','head','merged'),'tree')
        with patch.object(gate.common,'git',return_value=b'wrong\n'):
            with self.assertRaises(ValueError):gate.verify_merged(None,'base','head','merged')
        with patch.object(gate.common,'git',return_value=b'base\n'),\
                patch.object(gate.common,'tracked',side_effect=[{'file':('100644','a')},{'file':('100644','b')}]):
            with self.assertRaises(ValueError):gate.verify_merged(None,'base','head','merged')
