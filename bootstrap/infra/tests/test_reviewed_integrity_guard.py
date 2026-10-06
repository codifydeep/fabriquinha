import hashlib,json,subprocess,tempfile,unittest,os
from pathlib import Path
from product_attestation import sign

class ReviewedGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.key=self.root/'key';subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(self.key)],check=True,capture_output=True)
        self.git('init','-q');self.git('config','user.name','Guard Fixture');self.git('config','user.email','guard@example.invalid')
        public=subprocess.run(['openssl','pkey','-in',str(self.key),'-pubout'],check=True,capture_output=True).stdout.decode()
        self.write('scripts/ci/test-maintenance-public.pem',public)
        source=Path(os.environ['GOVERNANCE_CANDIDATE']) if os.environ.get('GOVERNANCE_CANDIDATE') else Path(__file__).parents[1]/'governance'
        for name in ('verify-test-maintenance.py','test-integrity-guard.sh'):self.write('scripts/ci/'+name,(source/name).read_text())
        self.write('tests/a.test.ts','test("preserved",()=>expect(value).toBe(1));\n');self.write('server/a.ts','value=1;\n')
        self.base=self.commit();self.guard=source/'test-integrity-guard.sh'
    def git(self,*args):return subprocess.run(['git',*args],cwd=self.repo,check=True,capture_output=True).stdout.decode().strip()
    def write(self,name,text):
        path=self.repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    def commit(self):self.git('add','.');self.git('commit','-qm','fixture');return self.git('rev-parse','HEAD')
    def attest(self):
        paths=['server/a.ts','tests/a.test.ts']
        p=dict(version=1,scope='reviewed_test_maintenance_only',base=self.base,author='quality_security',reviewer='techlead',source_manifest={n:hashlib.sha256((self.repo/n).read_bytes()).hexdigest() for n in paths},allowed_test_paths=['tests/a.test.ts'],removed_paths=[])
        self.write('.hermes/reviewed-test-maintenance.json',json.dumps(sign(p,self.key)))
    def check(self,passed):
        head=self.commit();r=subprocess.run(['bash',str(self.guard),self.base,head],cwd=self.repo,capture_output=True,text=True)
        self.assertEqual(r.returncode==0,passed,r.stdout+r.stderr)
    def test_unreviewed_assertion_change_denied(self):
        self.write('tests/a.test.ts','test("preserved",()=>expect(value).toBe(2));\n');self.check(False)
    def test_signed_exact_maintenance_allowed(self):
        self.write('tests/a.test.ts','test("preserved",()=>expect(value).toBe(2));\n');self.attest();self.check(True)
    def test_signed_ignored_test_still_denied(self):
        self.write('tests/a.test.ts','test.skip("preserved",()=>expect(value).toBe(2));\n');self.attest();self.check(False)
    def test_source_modified_after_attestation_denied(self):
        self.attest();self.write('server/a.ts','value=3;\n');self.check(False)
    def test_head_public_key_cannot_replace_trust(self):
        self.attest();self.write('scripts/ci/test-maintenance-public.pem','forged');self.check(False)
    def test_historical_receipt_does_not_block_unrelated_next_pr(self):
        self.attest();self.base=self.commit();self.write('server/a.ts','value=2;\n');self.check(True)
    def test_reviewer_cannot_self_approve(self):
        self.attest();path=self.repo/'.hermes/reviewed-test-maintenance.json';r=json.loads(path.read_text());r['payload']['reviewer']='quality_security';path.write_text(json.dumps(r));self.check(False)
