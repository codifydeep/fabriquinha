import json,unittest,sqlite3
from product_platform import configs,validate,requests

class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.spec=dict(capability='frontend',brief='Prepare the full frontend validator without dropping backend coverage or changing the established test discovery contract. Preserve every existing compiler constraint.',dependencies={},devDependencies={},targets=['server','shared','web','tests'])
        self.files={'package.json':json.dumps(dict(scripts={'test':'vitest run','lint':'eslint server tests','typecheck':'tsc --noEmit','build':'tsc -p tsconfig.build.json'})),
            'tsconfig.json':json.dumps(dict(compilerOptions={'strict':True,'lib':['ES2022']},include=['server/**/*.ts','tests/**/*.ts'])),
            'tsconfig.build.json':json.dumps(dict(compilerOptions={'strict':True,'rootDir':'server'},include=['server/**/*.ts']))}
    def test_additive_roots_preserve_strict_and_existing_discovery(self):
        result=configs(self.files,self.spec);ts=json.loads(result['tsconfig.json'])
        self.assertTrue(ts['compilerOptions']['strict']);self.assertIn('tests/**/*.ts',ts['include']);self.assertIn('web/**/*.tsx',ts['include']);self.assertIn('DOM',ts['compilerOptions']['lib'])
        self.assertEqual(json.loads(result['package.json'])['scripts']['test'],'vitest run')
    def test_no_arbitrary_shell_url_or_coverage_shrink(self):
        for spec in (dict(self.spec,shell='arbitrary'),dict(self.spec,targets=['web']),dict(self.spec,dependencies={'evil':'https://invalid'})):
            with self.assertRaises((PermissionError,ValueError)):validate(spec,'frontend')

    def test_request_scan_excludes_escalation_journal(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE records(key TEXT PRIMARY KEY,value TEXT)')
        request=dict(state='VALIDATING',task='t_1',capability='frontend',parent='TDD-10')
        db.executemany('INSERT INTO records VALUES(?,?)',[
            ('platform-request:abc',json.dumps(request)),
            ('platform-request:abc:escalation',json.dumps('t_cto')),
            ('platform-request:abc:escalation:incident',json.dumps({'task':'t_other'}))])
        self.assertEqual(list(requests(db)),[('platform-request:abc',request)])

    def test_corrupt_root_request_is_not_silently_ignored(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE records(key TEXT PRIMARY KEY,value TEXT)')
        db.execute('INSERT INTO records VALUES(?,?)',('platform-request:abc',json.dumps('t_wrong')))
        with self.assertRaisesRegex(ValueError,'invalid platform request'):list(requests(db))
