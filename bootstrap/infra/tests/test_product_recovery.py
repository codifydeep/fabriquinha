import json,sqlite3,unittest
from unittest.mock import Mock,patch
from product_recovery import dependencies,apply_dependencies,request_spec,recovery_key
from product_workspace import Workspace
from product_rework import Rework

class RecoveryContracts(unittest.TestCase):
    def test_budget_explains_delta_without_relaxing_limit(self):
        with self.assertRaisesRegex(ValueError,'received 9 packages, maximum 8.*Omitted existing dependencies are preserved'):
            dependencies(dict(dependencies={f'pkg{i}':'1.0.0' for i in range(9)},devDependencies={}))
    def test_dependency_versions_are_exact_registry_only(self):
        for value in ('latest','^8.0.0','file:/tmp','https://example.com/x','git+ssh://x',None):
            with self.subTest(value=value),self.assertRaises(ValueError):dependencies(dict(dependencies={'ws':value},devDependencies={}))
        self.assertEqual(dependencies(dict(dependencies={'ws':'8.18.3'},devDependencies={})),dict(dependencies={'ws':'8.18.3'},devDependencies={}))
    def test_malformed_maps_and_extra_authority_denied(self):
        for spec in ({'dependencies':None,'devDependencies':{}},{'dependencies':{},'devDependencies':{},'scripts':{}},{'dependencies':{'ws':'1.0.0'},'devDependencies':{'ws':'1.0.0'}}):
            with self.assertRaises(ValueError):dependencies(spec)
    def test_preserve_scripts_and_existing_dependencies(self):
        original=dict(scripts=dict(test='vitest run',lint='eslint server tests',typecheck='tsc --noEmit',build='tsc -p tsconfig.build.json'),dependencies={'fastify':'^5'},private=True)
        result=json.loads(apply_dependencies(json.dumps(original),dict(dependencies={'ws':'8.18.3'},devDependencies={})))
        self.assertEqual(result['scripts'],original['scripts']);self.assertEqual(result['dependencies']['fastify'],'^5');self.assertTrue(result['private'])
        original['scripts']['test']='vitest run tests/only.test.ts'
        with self.assertRaises(PermissionError):apply_dependencies(json.dumps(original),dict(dependencies={},devDependencies={}))
    def test_actionable_brief_required(self):
        with self.assertRaises(ValueError):request_spec(dict(brief='fix',dependencies={},devDependencies={}))
    def test_recovery_is_bound_to_exact_head(self):
        self.assertNotEqual(recovery_key(dict(pr=24,head='a'),{}),recovery_key(dict(pr=24,head='b'),{}))

class EmptyArtifactTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.who=dict(attempt='a',task='t',run=1,claim='c',profile='backend_data',mode='implementation')
        self.binding=Mock(return_value=self.who);self.binding.cards={'t':{'removable_empty_artifacts':['server/empty.test.ts']}}
        self.w=Workspace(self.db,self.binding);self.w.seed('a','t','backend_data','a'*40,{'server/empty.test.ts':'','tests/old.test.ts':'test'},['tests/old.test.ts'])
        self.req={k:self.who[k] for k in ('attempt','task','run','claim')}
    def remove(self,path='server/empty.test.ts'):
        d=self.w.read_draft(self.req);return self.w.remove_empty_artifact(self.req,d['version'],d['sha256'],path,'Controller proved empty artifact absent from integrated baseline.')
    def test_only_registered_empty_artifact_removed(self):
        self.remove();self.assertEqual(self.w.read_draft(self.req)['files'],{'tests/old.test.ts':'test'})
    def test_real_test_preserved(self):
        with self.assertRaises(PermissionError):self.remove('tests/old.test.ts')
    def test_nonempty_artifact_preserved(self):
        d=self.w.read_draft(self.req);self.w.edit(self.req,d['version'],d['sha256'],{'server/empty.test.ts':'test'})
        with self.assertRaises(PermissionError):self.remove()
    def test_reviewer_denied(self):
        d=self.w.read_draft(self.req);self.who.update(profile='techlead',mode='review')
        with self.assertRaises(PermissionError):self.w.remove_empty_artifact(self.req,d['version'],d['sha256'],'server/empty.test.ts','Reason with sufficient concrete detail.')
    def test_stale_version_denied(self):
        with self.assertRaises(ValueError):self.w.remove_empty_artifact(self.req,10,'wrong','server/empty.test.ts','Reason with sufficient concrete detail.')

class ReworkPublicationTests(unittest.TestCase):
    def test_preserved_draft_cannot_be_taken_from_other_author(self):
        c=Rework();c.source_files=Mock(return_value={});c.cfg={'cards':{'t':{'rework_head':'head','author':'frontend'}}}
        with self.assertRaises(PermissionError):c.recovery_files(dict(head='head',author='backend_data'),dict(draft_task='t'))
    def test_original_author_draft_is_used_for_next_diagnosis(self):
        c=Rework();c.source_files=Mock(return_value={'server/a.ts':'old'});c.cfg={'attempt':'a','cards':{'t':{'rework_head':'head','author':'backend_data'}}};c.private=Mock()
        c.private.execute.return_value.fetchone.return_value=(json.dumps({'server/a.ts':'preserved work'}),)
        self.assertEqual(c.recovery_files(dict(head='head',author='backend_data'),dict(draft_task='t')),{'server/a.ts':'preserved work'})
    def test_changed_pr_head_never_published(self):
        c=Rework();c.get=Mock(return_value=None)
        card=dict(rework_pr=24,rework_head='old',release_base='base')
        pr=dict(state='open',base=dict(ref='release/v0.1',sha='base'),head=dict(ref='codex/work',sha='foreign',repo=dict(full_name='codifydeep/truco-online')))
        with patch('product_autonomy.api',return_value=pr) as api:
            with self.assertRaises(PermissionError):c.publish_rework('task',card,{})
            self.assertEqual(api.call_count,1)

class ProposalTests(unittest.TestCase):
    def test_return_to_author_requires_independent_exact_approval(self):
        from test_product_team import TeamTests
        fixture=TeamTests();fixture.setUp()
        try:
            fixture.team.packet=Mock(return_value=dict(head='a'*40,allowed_actions=['return_to_author']))
            req=dict(fixture.req,action='return_to_author',specification=dict(brief='Preserve all baseline tests. Add a regression for protocol fragmentation, use approved ws dependency and validate the entire project before resubmitting.',dependencies={'ws':'8.18.3'},devDependencies={}))
            result=fixture.team.handle(req)
            fixture.binding.return_value=dict(task='t',run=2,profile='cto',mode='review')
            approved=fixture.team.handle(dict(fixture.identity,operation='team_decide',proposal_sha256=result['proposal_sha256'],decision='approve',reason='Independent CTO review: concrete regression, registry dependency, preserved baseline and same PR.'))
            self.assertFalse(approved['merge_authorized'])
            with self.assertRaises(PermissionError):fixture.team.handle(dict(req,operation='team_propose'))
        finally:fixture.doCleanups()
