import json,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from product_workspace import Workspace,validate_files

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.current=dict(attempt='trial',task='t_one',run=1,claim='live',profile='backend_data',mode='implementation')
        self.request={k:self.current[k] for k in ('attempt','task','run','claim')}
        self.w=Workspace(self.db,lambda request:self.current)
        self.w.seed('trial','t_one','backend_data','a'*40,{'src/app.mjs':'export const n=1;','tests/base.test.mjs':'baseline'},['tests/base.test.mjs'])
    def edit(self,replacements):
        d=self.w.read_draft(self.request);return self.w.edit(self.request,d['version'],d['sha256'],replacements)
    def test_edit_and_cas(self):
        d=self.w.read_draft(self.request);self.edit({'src/app.mjs':'export const n=2;'})
        with self.assertRaises(ValueError):self.w.edit(self.request,d['version'],d['sha256'],{'src/app.mjs':'stale'})
    def test_preserve_existing_tests(self):
        with self.assertRaises(PermissionError):self.edit({'tests/base.test.mjs':'skip'})
    def test_no_delete(self):
        with self.assertRaises(ValueError):self.edit({'tests/base.test.mjs':None})
    def test_foreign_task(self):
        self.request['task']='t_other'
        with self.assertRaises(PermissionError):self.w.read_draft(self.request)
    def test_stale_claim(self):
        self.current['claim']='new'
        with self.assertRaises(PermissionError):self.w.freeze(self.request,0)
    def test_reviewer_cannot_edit(self):
        self.current.update(mode='review',profile='techlead')
        with self.assertRaises(PermissionError):self.w.edit(self.request,0,'x',{'src/app.mjs':'hack'})
    def test_snapshot_survives_author_rework_and_restart(self):
        first=self.w.freeze(self.request,0);self.assertEqual(first,self.w.freeze(self.request,0))
        self.edit({'src/app.mjs':'new source'})
        self.w=Workspace(self.db,lambda request:self.current)
        self.current.update(mode='review',profile='techlead')
        self.assertEqual(self.w.inspect(self.request,first['revision'])['src/app.mjs'],'export const n=1;')
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_submissions').fetchone()[0],1)
    def test_self_review_denied(self):
        r=self.w.freeze(self.request,0);self.current['mode']='review'
        with self.assertRaises(PermissionError):self.w.inspect(self.request,r['revision'])
    def test_wrong_independent_reviewer_denied(self):
        r=self.w.freeze(self.request,0);self.current.update(mode='review',profile='designer')
        with self.assertRaises(PermissionError):self.w.inspect(self.request,r['revision'])
    def test_path_escape(self):
        for name in ('../escape','src/../../escape','/tmp/hack','src/.env','src//x','src/./x','src\\hack','.github/workflows/x','src/node_modules/x'):
            with self.subTest(name=name),self.assertRaises(ValueError):validate_files({name:'bad'})
    def test_unprotected_baseline_test_denied(self):
        with self.assertRaises(ValueError):self.w.seed('trial','t_two','backend_data','a'*40,{'tests/old.mjs':'test'},[])
