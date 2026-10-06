import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from product_build_contract import enable_shared_build
from product_build_recovery import prepare
from product_validation_jobs import schema
from product_workspace import Workspace,digest

class BuildRecoveryTests(unittest.TestCase):
    def test_only_compilation_scope_is_widened(self):
        old=dict(extends='./tsconfig.json',include=['server/**/*.ts'],compilerOptions=dict(rootDir='server',strict=True))
        new=json.loads(enable_shared_build(json.dumps(old)))
        self.assertEqual(new['compilerOptions'],dict(rootDir='.',strict=True))
        self.assertEqual(new['include'],['server/**/*.ts','shared/**/*.ts'])
        self.assertEqual(new['extends'],old['extends'])
        with self.assertRaises(PermissionError):enable_shared_build('{"include":["somewhere"],"compilerOptions":{"rootDir":"/"}}')
    def test_approved_config_transition_preserves_source_and_old_evidence(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        files={'package.json':'{}','package-lock.json':'{}','tsconfig.json':'{}','eslint.config.mjs':'export default [];','tsconfig.build.json':'{"extends":"./tsconfig.json","include":["server/**/*.ts"],"compilerOptions":{"rootDir":"server"}}','server/a.ts':'original source','tests/a.test.ts':'unchanged test'}
        protected=['package.json','tsconfig.json','tsconfig.build.json','tests/a.test.ts']
        Workspace(db,Mock()).seed('attempt','t','backend_data','a'*40,files,protected)
        schema(db)
        c=Mock();c.private=db;c.cfg={'attempt':'attempt'}
        proposal=dict(action='enable_shared_build',head='a'*40,specification=dict(target_task='t',draft_sha256=digest(files),brief='x'*120))
        card=dict(files=files,validation_image='old')
        self.assertIsNone(prepare(c,'t',card,proposal,'cto-decision'))
        job,request=db.execute('SELECT id,request FROM product_validation_jobs').fetchone()
        self.assertEqual(json.loads(request)['draft_sha256'],digest(files))
        configs={n:files[n] for n in ('package.json','package-lock.json','tsconfig.json','eslint.config.mjs','tsconfig.build.json')}
        configs['tsconfig.build.json']=enable_shared_build(configs['tsconfig.build.json'])
        with db:db.execute("UPDATE product_validation_jobs SET state='READY',result=?",(json.dumps(dict(image='sha256:'+'b'*64,configs=configs)),))
        updated=prepare(c,'t',card,proposal,'cto-decision')
        self.assertNotEqual(updated['validation_image'],'old')
        version,raw=db.execute('SELECT version,files FROM product_drafts').fetchone()
        self.assertEqual(version,1);self.assertEqual(json.loads(raw)['server/a.ts'],'original source');self.assertEqual(json.loads(raw)['tests/a.test.ts'],'unchanged test')
        self.assertEqual(json.loads(db.execute('SELECT before_files FROM product_config_transitions').fetchone()[0]),files)
        prepare(c,'t',updated,proposal,'cto-decision')
        self.assertEqual(db.execute('SELECT version FROM product_drafts').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM product_config_transitions').fetchone()[0],1)
