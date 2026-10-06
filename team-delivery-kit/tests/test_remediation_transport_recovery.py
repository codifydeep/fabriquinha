import copy
import unittest
from broker.remediation_transport_recovery import qualify,isolated_mounts


class ChangedTransportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.c=dict(original_depth=2,cto='cto',required_paths=['source'])
        self.s=dict(stage='blocked',category='ValueError',issue_id='issue',wakeup_id='wake')
        self.t=dict(status='failed',failure_reason='agent_error.provider_server_error',agent_id='cto',issue_id='issue',wakeup_id='wake')
        self.reads=dict(source=dict(lines=10,total_lines=10))
        self.e=dict(status=502,category='structured_decision_response_invalid',structured_rejection_category='nonterminal_or_non_json_response',
                    finish_reason='stop',strict_schema=True,decision_schema='delivery_decision_v1',tool_count=18)

    def test_exact_failure_can_qualify_without_approval_or_depth_reset(self):
        before=copy.deepcopy((self.c,self.s,self.t,self.reads,self.e))
        qualify(self.c,self.s,self.t,self.reads,self.e)
        self.assertEqual(before,(self.c,self.s,self.t,self.reads,self.e))

    def test_canary_allows_only_fixed_empty_tmpfs_not_inherited_volume(self):
        info=dict(Mounts=[],HostConfig=dict(Tmpfs={'/opt/data':'size=1m,mode=0700'}))
        self.assertTrue(isolated_mounts(info))
        for mount in (dict(Type='volume',Destination='/opt/data'),dict(Type='bind',Destination='/opt/data'),
                      dict(Type='tmpfs',Destination='/secrets')):
            self.assertFalse(isolated_mounts({**info,'Mounts':[mount]}))
        self.assertFalse(isolated_mounts(dict(Mounts=[],HostConfig={})))

    def test_repeated_or_accepted_plan_rejected(self):
        for extra in (dict(typed_transport_recovery={'used':True}),dict(plan={'accepted':True}),dict(stage='awaiting_plan')):
            with self.assertRaises(ValueError):qualify(self.c,{**self.s,**extra},self.t,self.reads,self.e)

    def test_incomplete_reads_wrong_identity_or_other_failure_rejected(self):
        with self.assertRaises(ValueError):qualify(self.c,self.s,self.t,{},self.e)
        for extra in (dict(agent_id='author'),dict(status='completed'),dict(wakeup_id='old')):
            with self.assertRaises(ValueError):qualify(self.c,self.s,{**self.t,**extra},self.reads,self.e)
        for extra in (dict(status=402),dict(finish_reason='length'),dict(strict_schema=False)):
            with self.assertRaises(ValueError):qualify(self.c,self.s,self.t,self.reads,{**self.e,**extra})
