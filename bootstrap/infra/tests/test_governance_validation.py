import json,unittest
from unittest.mock import Mock
import test_product_team
from product_workspace import digest

class GovernanceValidationTests(unittest.TestCase):
    setUp=test_product_team.TeamTests.setUp
    def test_governance_cannot_use_test_maintenance_scope_or_skip_proof(self):
        # Exercise the generic handler with a real per-run independent identity.
        p=dict(action='publish_governance',author='devops',changes={'AGENTS.md':'scope'})
        self.team.db.execute('INSERT INTO team_decisions VALUES(?,?,NULL,?)',('t',json.dumps(p),'IN_REVIEW'));self.team.db.commit()
        self.team.binding=Mock(return_value=dict(task='t',profile='cto',mode='review',run=7))
        self.team.packet=Mock(return_value={})
        req=dict(attempt='a',task='t',run=7,claim='x',proposal_sha256=digest(p))
        with self.assertRaises(PermissionError):self.team.handle(dict(req,operation='team_decide',decision='approve',reason='Evidence-based independent review. '*3))
        self.team.runner=Mock();self.team.governance_runner=Mock(return_value=dict(passed=True));self.team.governance_image='sha256:'+'a'*64
        self.assertTrue(self.team.handle(dict(req,operation='team_validate'))['passed'])
        self.assertEqual(self.team.handle(dict(req,operation='team_decide',decision='approve',reason='Evidence-based independent review. '*3))['decision'],'approve')
