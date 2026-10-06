import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from product_team import Team,refresh_manifest
from product_workspace import digest

class TeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        (root/'team-packets').mkdir();self.packet=dict(head='a'*40,allowed_actions=['refresh_generated_manifest'],refreshable=['scripts/ci/run-project-checks.sh'],files={'.hermes/team/generated-manifest.json':json.dumps({'files':{'scripts/ci/run-project-checks.sh':'old','other':'preserve'}}),'scripts/ci/run-project-checks.sh':'run all tests\n'})
        raw=json.dumps(self.packet).encode();(root/'team-packets/t.json').write_bytes(raw)
        self.binding=Mock(return_value=dict(task='t',run=1,profile='techlead',mode='implementation'))
        self.binding.cards={'t':{'packet_sha256':hashlib.sha256(raw).hexdigest()}}
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.team=Team(root,self.binding,None,self.db);self.team.recover=Mock()
        self.identity=dict(attempt='a',task='t',run=1,claim='lock')
        self.req=dict(self.identity,operation='team_propose',action='refresh_generated_manifest',specification={},reason='The actual generated drift points to the changed script. Preserve all assertions and the drift checker; reconcile only its exact content digest after independent review.')
    def test_refresh_preserves_other_entries(self):
        changes=refresh_manifest(self.packet);self.assertEqual(list(changes),['.hermes/team/generated-manifest.json'])
        files=json.loads(next(iter(changes.values())))['files'];self.assertEqual(files['other'],'preserve');self.assertEqual(files['scripts/ci/run-project-checks.sh'],hashlib.sha256(b'run all tests\n').hexdigest())
    def test_status_supplies_controller_computed_hashes(self):
        status=self.team.handle(dict(self.identity,operation='team_status'))
        self.assertEqual(status['file_sha256']['scripts/ci/run-project-checks.sh'],hashlib.sha256(b'run all tests\n').hexdigest())
    def test_author_receives_full_changes_requested_verdict(self):
        sha=self.team.handle(self.req)['proposal_sha256']
        self.binding.return_value=dict(task='t',run=2,profile='cto',mode='review')
        reason='The proposed operation does not address the observed failure. Supply an executable diagnosis with preserved test discovery.'
        self.team.handle(dict(self.identity,operation='team_decide',proposal_sha256=sha,decision='request_changes',reason=reason))
        self.binding.return_value=dict(task='t',run=3,profile='techlead',mode='implementation')
        status=self.team.handle(dict(self.identity,operation='team_status'))
        self.assertEqual(status['latest_review']['reason'],reason)
        self.assertEqual(status['latest_review']['proposal_sha256'],sha)
        self.assertEqual(status['latest_review']['reviewer'],'cto')
    def test_prior_review_survives_revised_proposal(self):
        sha=self.team.handle(self.req)['proposal_sha256']
        self.binding.return_value=dict(task='t',run=2,profile='cto',mode='review')
        reason='Preserve the test configuration and explain the independently verifiable evidence for this corrected diagnosis.'
        self.team.handle(dict(self.identity,operation='team_decide',proposal_sha256=sha,decision='request_changes',reason=reason))
        self.binding.return_value=dict(task='t',run=3,profile='techlead',mode='implementation')
        self.team.handle(dict(self.req,reason='Revised evidence-backed diagnosis: preserve discovery, reconcile the generated hash only, and validate the full immutable script.'))
        status=self.team.handle(dict(self.identity,operation='team_status'))
        self.assertEqual(status['latest_review']['reason'],reason)
        self.assertNotEqual(status['proposal_sha256'],status['latest_review']['proposal_sha256'])
    def test_no_silent_noop(self):
        self.packet['files']['.hermes/team/generated-manifest.json']=refresh_manifest(self.packet)['.hermes/team/generated-manifest.json']
        with self.assertRaises(ValueError):refresh_manifest(self.packet)
    def test_author_cannot_approve(self):
        self.team.handle(self.req)
        with self.assertRaises(PermissionError):self.team.handle(dict(self.identity,operation='team_decide',proposal_sha256='x',decision='approve',reason='x'*80))
    def test_unknown_action_denied(self):
        with self.assertRaises(PermissionError):self.team.handle(dict(self.req,action='merge_without_ci'))
    def test_idempotent_proposal(self):
        self.team.handle(self.req);self.team.handle(self.req)
        self.assertEqual(self.db.execute('select count(*) from team_decisions').fetchone()[0],1)
    def test_proposal_conflict_denied(self):
        self.team.handle(self.req)
        with self.assertRaises(PermissionError):self.team.handle(dict(self.req,reason='Different proposal '*10))
    def test_stale_review_denied(self):
        self.team.handle(self.req);self.binding.return_value=dict(task='t',run=2,profile='cto',mode='review')
        with self.assertRaises(PermissionError):self.team.handle(dict(self.identity,operation='team_decide',proposal_sha256='old',decision='approve',reason='Verified scope '*10))
    def test_independent_decision_exact_proposal(self):
        sha=self.team.handle(self.req)['proposal_sha256'];self.binding.return_value=dict(task='t',run=2,profile='cto',mode='review')
        result=self.team.handle(dict(self.identity,operation='team_decide',proposal_sha256=sha,decision='approve',reason='Verified immutable proposal and exact script; no changes to tests or assertion discovery.'))
        self.assertFalse(result['merge_authorized'])
    def test_extra_authority_denied(self):
        with self.assertRaises(ValueError):self.team.handle(dict(self.req,specification={'shell':'rm -rf /'}))
    def test_packet_tampering_denied(self):
        (Path(self.tmp.name)/'team-packets/t.json').write_text('{}')
        with self.assertRaises(PermissionError):self.team.handle(self.req)
