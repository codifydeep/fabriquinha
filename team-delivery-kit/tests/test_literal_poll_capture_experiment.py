import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import literal_poll_capture_experiment as experiment


class PollCaptureExperimentTests(unittest.TestCase):
    def fixture(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);root=Path(folder.name)
        harness="""const vm=require('vm'), fs=require('fs');
const source=fs.readFileSync(%(source_path)s,'utf8');
const line={textContent:''}, handlers={}, requests=[];let intervalCallback;
const document={getElementById:id=>id==='feedback-latest-match'?line:
 {addEventListener:(event,fn)=>handlers[id]=fn}};
const fetch=url=>new Promise(resolve=>requests.push({url,resolve}));
vm.runInNewContext(source,{document,fetch,setInterval:fn=>{intervalCallback=fn;}});
async function flush(){for(let i=0;i<20;i++)await Promise.resolve();}
function tick(){intervalCallback();}
function latestCount(){return requests.length;}
function complete(i,id){requests[i].resolve({json:()=>Promise.resolve({latest_id:id})});}
(async()=>{
  const snap={executed:true};
  snap.initial_requests=latestCount();
  complete(0,7);await flush();
  tick();await flush();
  snap.poll_requests = latestCount();
  complete(1,null);await flush();
  handlers['filter-open']();handlers['filter-completed']();
  complete(requests.length-1,11);await flush();
  complete(requests.length-2,4);await flush();
  snap.stale_guard_text=line.textContent;
  process.stdout.write(JSON.stringify(snap));
})().catch(()=>{process.exitCode=1;});
"""
        raw=('PREFIX = "Newest matching: "\nNODE_HARNESS = '+repr(harness)+'\nclass Checks:\n'
            ' def test_stale_response_never_overwrites_newer_query(self):\n'
            '  self.assertEqual(self.report["stale_guard_text"], PREFIX + "#11")\n'
            ' def test_poll_and_filter_change_request_latest(self):\n'
            '  self.assertEqual(self.report["initial_requests"], 1)\n'
            '  self.assertGreaterEqual(self.report["poll_requests"], 3)\n').encode()
        (root/'tests').mkdir();(root/'tests/test.py').write_bytes(raw)
        manifest=json.dumps({'files':{'tests/test.py':dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))}},sort_keys=True).encode()
        (root/'manifest.json').write_bytes(manifest)
        return root,hashlib.sha256(manifest).hexdigest(),raw

    def test_capture_timing_is_measured_without_mutating_snapshot_or_submitting_a_test(self):
        root,manifest,raw=self.fixture()
        value=experiment.run(root,manifest,'tests/test.py','a'*64)
        self.assertTrue(value['hypothesis_supported']);self.assertTrue(value['snapshot_unchanged'])
        self.assertEqual((root/'tests/test.py').read_bytes(),raw)
        self.assertEqual(value['reports']['original']['guarded']['poll_requests'],2)
        self.assertEqual(value['reports']['after_capture']['guarded']['poll_requests'],2)
        self.assertEqual(value['reports']['before_capture']['guarded']['poll_requests'],3)
        for flag in experiment.protocol.FALSE_FLAGS:self.assertIs(value[flag],False)
        self.assertEqual(value['diagnosis_sha256'],'a'*64)

    def test_ambiguous_assignment_or_missing_anchor_fails_closed(self):
        for text in ('console.log(1);','  snap.poll_requests = latestCount();\n'*2):
            with self.assertRaises(ValueError):experiment.variants(text)

    def test_measured_ordering_or_initial_request_regressions_cannot_support_hypothesis(self):
        root,manifest,_=self.fixture();value=experiment.run(root,manifest,'tests/test.py','a'*64)
        value['reports']['before_capture']['guarded']['stale_guard_text']='wrong'
        self.assertFalse(experiment.supports(value['assertion_bindings'],value['reports']))
        root,manifest,_=self.fixture();value=experiment.run(root,manifest,'tests/test.py','a'*64)
        value['reports']['before_capture']['guarded']['initial_requests']=2
        self.assertFalse(experiment.supports(value['assertion_bindings'],value['reports']))

    def test_changed_manifest_or_noncanonical_diagnosis_is_rejected(self):
        root,manifest,_=self.fixture()
        for identity in ('bad','a'*63,'A'*64):
            with self.assertRaises(ValueError):experiment.run(root,manifest,'tests/test.py',identity)
        (root/'tests/test.py').write_text('changed')
        with self.assertRaises(ValueError):experiment.run(root,manifest,'tests/test.py','a'*64)
