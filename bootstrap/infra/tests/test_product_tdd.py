import hashlib,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from product_workspace import Workspace
from product_tdd import TDD

class TDDTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.claim=dict(attempt='trial',task='t_one',run=1,claim='active',mode='implementation',profile='backend_data')
        self.req={k:self.claim[k] for k in ('attempt','task','run','claim')}
        self.w=Workspace(self.db,lambda request:self.claim)
        self.w.seed('trial','t_one','backend_data','a'*40,{'src/a.mjs':'red','tests/a.test.mjs':'assert'},['tests/a.test.mjs'])
        self.t=TDD(self.w,'sha256:'+'b'*64);self.calls=0
    def runner(self,files,image):
        self.calls+=1;red=files['src/a.mjs']=='red'
        return dict(image=image,snapshot={n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()},exit_code=1 if red else 0,
            output='# tests 1\n# fail '+('1\nERR_ASSERTION' if red else '0\n'))
    def change(self):
        d=self.w.read_draft(self.req);self.w.edit(self.req,d['version'],d['sha256'],{'src/a.mjs':'green'})
    def test_full_sequence_and_reopen(self):
        self.assertTrue(self.t.execute(self.req,'red',self.runner)['accepted']);self.change()
        self.assertTrue(self.t.execute(self.req,'green',self.runner)['accepted'])
        self.assertTrue(self.t.execute(self.req,'suite',self.runner)['accepted'])
        self.assertTrue(TDD(self.w,self.t.image).submission_evidence(self.req)['accepted'])
    def test_no_green_without_red(self):
        self.change()
        with self.assertRaises(PermissionError):self.t.execute(self.req,'green',self.runner)
    def test_no_suite_without_green(self):
        self.t.execute(self.req,'red',self.runner);self.change()
        with self.assertRaises(PermissionError):self.t.execute(self.req,'suite',self.runner)
    def test_idempotent_test(self):
        a=self.t.execute(self.req,'red',self.runner);self.assertEqual(a,self.t.execute(self.req,'red',self.runner));self.assertEqual(self.calls,1)
    def test_infra_failure_not_red(self):
        def fail(files,image):
            r=self.runner(files,image);r['output']='Cannot start runtime';return r
        self.assertFalse(self.t.execute(self.req,'red',fail)['accepted'])
    def test_image_mismatch(self):
        def fail(files,image):
            r=self.runner(files,image);r['image']='other';return r
        with self.assertRaises(PermissionError):self.t.execute(self.req,'red',fail)
    def test_skipped_tests_rejected(self):
        def skip(files,image):
            r=self.runner(files,image);r['output']+='\n# skipped 1\n';return r
        self.assertFalse(self.t.execute(self.req,'red',skip)['accepted'])
    def test_claim_revoked_during_test(self):
        def revoke(files,image):
            r=self.runner(files,image);self.claim['claim']='revoked';return r
        with self.assertRaises(PermissionError):self.t.execute(self.req,'red',revoke)
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_test_receipts').fetchone()[0],0)
    def test_tests_changed_requires_new_red(self):
        self.t.execute(self.req,'red',self.runner)
        d=self.w.read_draft(self.req);self.w.edit(self.req,d['version'],d['sha256'],{'tests/new.test.mjs':'new'})
        with self.assertRaises(PermissionError):self.t.execute(self.req,'green',self.runner)
    def test_changed_source_invalidates_suite(self):
        self.t.execute(self.req,'red',self.runner);self.change();self.t.execute(self.req,'green',self.runner);self.t.execute(self.req,'suite',self.runner)
        d=self.w.read_draft(self.req);self.w.edit(self.req,d['version'],d['sha256'],{'src/a.mjs':'changed'})
        with self.assertRaises(PermissionError):self.t.submission_evidence(self.req)
