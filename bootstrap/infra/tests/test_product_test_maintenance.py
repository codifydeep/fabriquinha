import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from product_test_maintenance import proposed_files,validate_proposal,apply,schema
from product_workspace import digest,Workspace
from product_case_inventory import inventory,compare

def output(files,status='passed'):
    return json.dumps({'testResults':[{'name':'/tmp/work/tests/a.test.ts','assertionResults':[{'fullName':'keeps contract','status':status,'failureMessages':['AssertionError: expected 2'] if status=='failed' else []}]}]})

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.files={'server/a.ts':'export const a=1;','tests/a.test.ts':'test("keeps contract",()=>expect(a).toBe(1));'}
        self.packet=dict(target_task='t',draft_sha256=digest(self.files),allowed_contract_sources=['card:t'],validation_image='sha256:'+'a'*64)
        self.spec=dict(target_task='t',draft_sha256=digest(self.files),brief='Align the test with the already approved technical contract while preserving all existing cases and proving behavioral Red before the implementation correction.',replacements={'tests/a.test.ts':'test("keeps contract",()=>expect(a).toBe(2));'},renames={},case_mapping={},contract_sources=['card:t'],change_kind='align_approved_contract')
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        Workspace(self.db,Mock()).seed('attempt','t','backend_data','a'*40,self.files,['tests/a.test.ts'])
        self.proposal=dict(task='maintenance',author='quality_security',head='a'*40,action='maintain_tests',specification=self.spec)
        self.who=dict(attempt='attempt',run=4,profile='techlead')
        def runner(files,image):
            failed=files['tests/a.test.ts']!=self.files['tests/a.test.ts']
            return dict(image=image,snapshot={k:hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()},exit_code=1 if failed else 0,output=output(files,'failed' if failed else 'passed'))
        self.runner=runner
    def test_exact_test_diff_only(self):
        updated=proposed_files(self.packet,self.spec,self.files)
        self.assertEqual(updated['server/a.ts'],self.files['server/a.ts']);self.assertNotEqual(updated['tests/a.test.ts'],self.files['tests/a.test.ts'])
    def test_configuration_code_and_skip_denied(self):
        for replacements in ({'server/a.ts':'malicious'},{'package.json':'{}'},{'tests/a.test.ts':'test.skip("bad",()=>{})'},{'tests/a.test.ts':''}):
            with self.assertRaises((ValueError,PermissionError)):proposed_files(self.packet,dict(self.spec,replacements=replacements),self.files)
    def test_business_scope_stale_source_and_unknown_contract_denied(self):
        for changes in ({'change_kind':'change_business_rules'},{'draft_sha256':'old'},{'contract_sources':['invented']}):
            with self.assertRaises((ValueError,PermissionError)):proposed_files(self.packet,dict(self.spec,**changes),self.files)
    def test_before_after_preserves_case_and_reports_real_red(self):
        receipt=validate_proposal(self.db,self.who,self.proposal,self.packet,self.runner)
        self.assertEqual(receipt['coverage']['preserved'],1)
        self.assertEqual(receipt['observed_red_cases'],['tests/a.test.ts::keeps contract'])
        self.assertEqual(receipt['phase'],'test_maintenance_validation_not_implementation_tdd')
        self.assertEqual(receipt,validate_proposal(self.db,self.who,self.proposal,self.packet,Mock(side_effect=AssertionError('must not rerun'))))
    def test_missing_case_or_collapsed_mapping_rejected(self):
        before={'a::one':{},'a::two':{}};after={'b::one':{}}
        with self.assertRaises(PermissionError):compare(before,after,{}, {})
        with self.assertRaises(ValueError):compare(before,after,{'a::one':'b::one','a::two':'b::one'}, {})
    def test_equivalent_rename_with_case_mapping(self):
        self.assertEqual(compare({'a::one':{}},{'b::new':{}},{'a::one':'b::new'},{'a':'b'})['preserved'],1)
    def test_ignored_cases_rejected(self):
        with self.assertRaises(ValueError):inventory({'output':output({},'skipped')})
    def test_non_green_baseline_is_not_silently_repaired(self):
        def bad(files,image):
            result=self.runner(files,image);result.update(exit_code=1,output=output(files,'failed'));return result
        with self.assertRaises(PermissionError):validate_proposal(self.db,self.who,self.proposal,self.packet,bad)
    def test_only_verified_new_empty_artifact_may_be_removed(self):
        files=dict(self.files,**{'shared/test/empty.test.ts':''})
        packet=dict(self.packet,draft_sha256=digest(files),removable_empty_artifacts=['shared/test/empty.test.ts'])
        spec=dict(self.spec,draft_sha256=digest(files),remove_empty=['shared/test/empty.test.ts'])
        self.assertNotIn('shared/test/empty.test.ts',proposed_files(packet,spec,files))
        for forbidden in (['tests/a.test.ts'],['unknown'],['shared/test/empty.test.ts','shared/test/empty.test.ts']):
            with self.assertRaises((PermissionError,ValueError)):proposed_files(packet,dict(spec,remove_empty=forbidden),files)
    def test_diagnostic_exposes_suite_failure_not_fictitious_assertion(self):
        from product_case_inventory import diagnostics
        r=dict(exit_code=1,output=json.dumps(dict(testResults=[dict(name='/tmp/work/tests/empty.test.ts',status='failed',message='No test suite found',assertionResults=[])])))
        diagnostic=diagnostics(r)
        self.assertEqual(diagnostic['classification'],'discovery_or_infrastructure')
        self.assertEqual(diagnostic['suite_failures'][0]['path'],'tests/empty.test.ts')
    def test_apply_requires_independent_execution(self):
        coordinator=SimpleNamespace(private=self.db,cfg={'attempt':'attempt'})
        with self.assertRaises(PermissionError):apply(coordinator,'t',{},self.proposal,dict(run=4),'maintenance')
    def test_apply_is_exact_archived_and_restart_safe(self):
        receipt=validate_proposal(self.db,self.who,self.proposal,self.packet,self.runner)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'team-packets').mkdir();(root/'team-packets/maintenance.json').write_text(json.dumps(self.packet))
            coordinator=SimpleNamespace(private=self.db,cfg={'attempt':'attempt'},root=root,register=Mock())
            verdict=dict(run=4,decision='approve',proposal_sha256=digest(self.proposal),reviewer='techlead')
            apply(coordinator,'t',{},self.proposal,verdict,'maintenance');apply(coordinator,'t',{},self.proposal,verdict,'maintenance')
            version,files=self.db.execute('SELECT version,files FROM product_drafts').fetchone();self.assertEqual(version,1)
            self.assertEqual(json.loads(files)['server/a.ts'],self.files['server/a.ts'])
            self.assertEqual(self.db.execute('SELECT before_files FROM test_maintenance_applied').fetchone()[0],json.dumps(self.files))
