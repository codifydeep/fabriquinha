import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publication_merge import validate_remote, validate_policy, authority


class PublicationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.repo={'allow_merge_commit':True}
        self.protection=dict(required_linear_history={'enabled':False},enforce_admins={'enabled':True},
            required_status_checks={'strict':True,'contexts':['governance','hermes-independent-review']},
            allow_force_pushes={'enabled':False},allow_deletions={'enabled':False})
    def test_compatible(self): self.assertTrue(validate_policy(self.repo,self.protection,[])['passed'])
    def test_linear(self):
        self.protection['required_linear_history']['enabled']=True
        with self.assertRaises(PermissionError): validate_policy(self.repo,self.protection,[])
    def test_ruleset(self):
        with self.assertRaises(PermissionError): validate_policy(self.repo,self.protection,[{'type':'required_linear_history'}])
    def test_missing_review(self):
        self.protection['required_status_checks']['contexts']=['governance']
        with self.assertRaises(PermissionError): validate_policy(self.repo,self.protection,[])
    def test_merge_disabled(self):
        self.repo['allow_merge_commit']=False
        with self.assertRaises(PermissionError): validate_policy(self.repo,self.protection,[])


class PublicationMergeTests(unittest.TestCase):
    def setUp(self):
        self.packet=dict(pr=14,repository='codifydeep/truco-online',head_sha='a'*40,base_sha='b'*40,
            head_branch='codex/restart-baseline-20260911',base_branch='main')
        self.pr=dict(number=14,state='open',merged=False,
            head=dict(sha='a'*40,ref=self.packet['head_branch'],repo=dict(full_name=self.packet['repository'])),
            base=dict(sha='b'*40,ref='main',repo=dict(full_name=self.packet['repository'])))
        self.ci=dict(headSha='a'*40,status='completed',conclusion='success',event='pull_request')

    def test_exact_foundation(self): validate_remote(self.packet,self.pr,self.ci)
    def test_exact_reconciliation(self):
        self.packet.update(pr=20,head_branch='codex/planning-reconciliation-20260917')
        self.pr['number']=20;self.pr['head']['ref']=self.packet['head_branch']
        validate_remote(self.packet,self.pr,self.ci)
        self.assertEqual(authority(dict(pr_number=20,integration_action='merge_reconciliation',author='techlead',reviewer='cto')),20)
    def test_unregistered_publication(self):
        with self.assertRaises(PermissionError):authority(dict(pr_number=21,integration_action='merge_reconciliation',author='techlead',reviewer='cto'))
    def test_exact_planning(self):
        self.packet.update(pr=19,head_branch='codex/planning-v0.1-20260916')
        self.pr['number']=19; self.pr['head']['ref']=self.packet['head_branch']
        validate_remote(self.packet,self.pr,self.ci)
    def test_planning_wrong_branch(self):
        self.packet['pr']=19;self.pr['number']=19
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
    def test_authority_is_fixed(self):
        card=dict(pr_number=19,integration_action='merge_planning',author='techlead',reviewer='cto')
        self.assertEqual(authority(card),19)
        card['integration_action']='merge_foundation'
        with self.assertRaises(PermissionError): authority(card)
    def test_no_self_review(self):
        with self.assertRaises(PermissionError): authority(dict(pr_number=19,integration_action='merge_planning',author='cto',reviewer='cto'))
    def test_stale_head(self):
        self.pr['head']['sha']='c'*40
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
    def test_stale_base(self):
        self.pr['base']['sha']='c'*40
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
    def test_manual_ci(self):
        self.ci['event']='workflow_dispatch'
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
    def test_other_pr(self):
        self.packet['pr']=19
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
    def test_fork(self):
        self.pr['head']['repo']['full_name']='other/repo'
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
    def test_failed_ci(self):
        self.ci['conclusion']='failure'
        with self.assertRaises(ValueError): validate_remote(self.packet,self.pr,self.ci)
