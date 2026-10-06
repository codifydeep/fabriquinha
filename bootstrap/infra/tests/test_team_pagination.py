import json,unittest
from unittest.mock import Mock
import test_product_team

class TeamPaginationTests(unittest.TestCase):
    setUp=test_product_team.TeamTests.setUp
    def test_large_lockfile_is_paged_not_spilled_and_feedback_stays_visible(self):
        self.team.packet=Mock(return_value=dict(files={'package-lock.json':'x'*145000,'package.json':'{}'},allowed_actions=['prepare_toolchain']))
        result=self.team.handle(dict(self.identity,operation='team_status'))
        self.assertLess(len(json.dumps(result)),12000)
        self.assertNotIn('package-lock.json',result['packet']['files'])
        self.assertEqual(result['packet']['file_manifest']['package-lock.json']['bytes'],145000)
        page=self.team.handle(dict(self.identity,operation='team_read_file',path='package-lock.json',offset=0))
        self.assertEqual(len(page['content']),2000);self.assertEqual(page['next_offset'],2000)
    def test_proposal_hash_covers_full_content_not_compact_view(self):
        from product_workspace import digest
        proposal=dict(changes={'large.md':'x'*20000},author='devops',action='publish_governance')
        self.db.execute('INSERT INTO team_decisions VALUES(?,?,NULL,?)',('t',json.dumps(proposal),'IN_REVIEW'));self.db.commit()
        result=self.team.handle(dict(self.identity,operation='team_status'))
        self.assertEqual(result['proposal_sha256'],digest(proposal));self.assertEqual(result['proposal']['changes'],{})
        self.assertEqual(self.team.handle(dict(self.identity,operation='team_read_proposal_file',path='large.md',offset=2000))['next_offset'],4000)
