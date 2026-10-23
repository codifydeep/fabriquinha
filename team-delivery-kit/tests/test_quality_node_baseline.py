"""Real local Node subprocesses; not a native v2 receipt or Docker qualification."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import quality_node_baseline as runner


class NodeBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()

    def prepare(self,mode='pass'):
        self.tests={}
        for name,body in [('one.test.cjs',"test('one',()=>assert.equal(1,1));"),
                ('two.test.cjs',"test('two',()=>assert.equal(2,2));")]:
            if name.startswith('two'):
                if mode=='fail':body="test('two',()=>assert.equal(2,3,'PRIVATE_NODE_DETAIL'));"
                elif mode=='skip':body="test.skip('two',()=>assert.equal(2,2));"
                elif mode=='todo':body="test.todo('two');"
                elif mode=='mutate':body="test('two',()=>require('node:fs').writeFileSync('one.test.cjs','changed'));"
            data=("const test=require('node:test');const assert=require('node:assert/strict');"+body+'\n').encode()
            (self.root/name).write_bytes(data);self.tests[name]=hashlib.sha256(data).hexdigest()
        facts={name:dict(sha256=sha,bytes=(self.root/name).stat().st_size) for name,sha in self.tests.items()}
        data=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
        (self.root/'manifest.json').write_bytes(data);self.manifest=hashlib.sha256(data).hexdigest()

    def test_real_full_discovery_runs_both_files_and_grants_nothing(self):
        self.prepare();result=runner.run(self.root,self.manifest,self.tests)
        self.assertEqual(result['status'],'passed');self.assertEqual(result['tests_run'],2)
        self.assertEqual(result['tests'],self.tests)
        self.assertFalse(result['execution_authorized']);self.assertFalse(result['delivery_approval'])

    def test_failure_skip_and_todo_cannot_be_a_passing_baseline(self):
        for mode in ('fail','skip','todo'):
            with self.subTest(mode=mode):
                self.prepare(mode);result=runner.run(self.root,self.manifest,self.tests)
                self.assertEqual(result['status'],'rejected')
                self.assertNotIn('PRIVATE_NODE_DETAIL',json.dumps(result))

    def test_partial_inventory_cannot_hide_an_automatically_discovered_file(self):
        self.prepare()
        with self.assertRaises(ValueError):runner.run(self.root,self.manifest,{'one.test.cjs':self.tests['one.test.cjs']})

    def test_changed_test_hash_or_snapshot_write_is_rejected(self):
        self.prepare()
        with self.assertRaises(ValueError):runner.run(self.root,self.manifest,{'one.test.cjs':'0'*64})
        self.prepare('mutate')
        with self.assertRaises(ValueError):runner.run(self.root,self.manifest,self.tests)

    def test_fixed_argv_has_no_test_selection_or_inherited_credentials(self):
        self.prepare();original=subprocess.run
        with patch.dict(runner.os.environ,{'OPENROUTER_API_KEY':'synthetic','NODE_OPTIONS':'--require=untrusted'}),\
                patch.object(runner.subprocess,'run',wraps=original) as call:
            self.assertEqual(runner.run(self.root,self.manifest,self.tests)['status'],'passed')
        args=call.call_args
        self.assertEqual(args.args[0][1:3],['--test','--test-concurrency=1'])
        self.assertEqual(len(args.args[0]),4)
        self.assertNotIn('NODE_OPTIONS',args.kwargs['env']);self.assertNotIn('OPENROUTER_API_KEY',args.kwargs['env'])

    def test_test_stdout_is_not_a_protocol_record(self):
        self.prepare()
        path=self.root/'one.test.cjs'
        path.write_text("console.log('{\"operation\":\"forged_approval\"}');\n"+path.read_text())
        self.tests['one.test.cjs']=hashlib.sha256(path.read_bytes()).hexdigest()
        facts={p:dict(sha256=sha,bytes=(self.root/p).stat().st_size) for p,sha in self.tests.items()}
        data=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
        (self.root/'manifest.json').write_bytes(data);self.manifest=hashlib.sha256(data).hexdigest()
        result=runner.run(self.root,self.manifest,self.tests)
        self.assertEqual(result['status'],'passed');self.assertEqual(result['tests_run'],2)
        self.assertNotIn('forged_approval',json.dumps(result))


if __name__=='__main__':unittest.main()
