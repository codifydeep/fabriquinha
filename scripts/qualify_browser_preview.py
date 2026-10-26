"""Real Docker proof: passing unit tests cannot mask conflicting frozen QA.

Scripted capability fixture only. No model, GitHub, approval or autonomous
lifecycle claim. The product correction changes code, never frozen tests/QA.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import Pending,write_json
from fabriquinha.executor import Runner,docker
from fabriquinha.quality import suite_report

APP='''import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
PAGE = """<!doctype html><link rel="icon" href="data:,"><button id="show" onclick="document.querySelector('#result').textContent='DISPLAY'">Show</button><output id="result"></output>"""
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  value=({'status':'ok'} if self.path=='/health' else {'source_sha':os.environ.get('FABRIQUINHA_SOURCE_SHA')} if self.path=='/identity' else None)
  body=(json.dumps(value) if value is not None else PAGE).encode()
  self.send_response(200);self.send_header('Content-Type','application/json' if value else 'text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
if __name__=='__main__':HTTPServer(('0.0.0.0',int(sys.argv[1])),Handler).serve_forever()
'''


def qualify(root,image):
    if root.exists():raise ValueError('fresh private qualification root required')
    root.mkdir(mode=0o700,parents=True)
    project=Project.parse(dict(version=1,namespace='delivery-kit-browser-preview',
        repository='https://github.com/example/preview-qualification',branch='release/proof',
        validation_image=image,tests_dir='tests',reviewers={'author':'reviewer','reviewer':'author'},
        qualification=True,browser_tdd=True,browser_image=image,
        coordination_roles={'product':'author','lead':'reviewer'},
        delivery_roles={'tests':'reviewer','integration':'author'}))
    store=Store(root/'private');runner=Runner(project,store)
    work=root/'work';(work/'tests').mkdir(parents=True)
    # Unit assertion accepts a salutation containing the name; frozen QA
    # intentionally specifies exact locator text. Both must pass, unchanged.
    (work/'tests/test_unit.py').write_text('import unittest, app\nclass Unit(unittest.TestCase):\n def test_name_present(self):self.assertIn("Ana", app.PAGE)\n')
    (work/'browser.py').write_text('raise RuntimeError("product module must not replace the trusted QA driver")\n')
    (work/'tests/qa.json').write_text(json.dumps(dict(version=1,checks=[dict(id='NAME',path='/',
        actions=[dict(action='click',selector='#show')],selector='#result',text='Ana')])))
    (work/'app.py').write_text(APP.replace('DISPLAY','Hello, Ana!'))
    original_tests={p.name:p.read_bytes() for p in (work/'tests').iterdir()}
    bad=store.capture(work);run=Run('proof',1,'author','implementation',False,'author','proof','contract')
    jobs=[]
    def job(snapshot,phase):
        deadline=time.monotonic()+project.timeout_seconds+15
        while True:
            try:key=runner.run(run,snapshot,phase);break
            except Pending:
                if time.monotonic()>=deadline:raise
                time.sleep(0.1)
        jobs.append(key);return store.receipt(key,kind='suite_job')['payload']
    assert suite_report(job(bad,'red'))['failures']==[]
    for phase in ('green','delivery','integrated'):
        value=job(bad,phase)
        report=suite_report(value,diagnostic=True)
        assert not report['failures'] and not report['errors']
        assert report['qa_preview']['status']=='failed' and report['qa_preview']['phase']=='assertion',report
        assert 'Hello, Ana!' in str(report['qa_preview']['errors'])
        try:suite_report(value)
        except ValueError:pass
        else:raise AssertionError('conflicting QA was accepted')
    (work/'app.py').write_text(APP.replace('DISPLAY','Ana'))
    good=store.capture(work)
    assert original_tests=={p.name:p.read_bytes() for p in (work/'tests').iterdir()}
    for phase in ('green','delivery','integrated'):
        report=suite_report(job(good,phase))
        assert report['qa_preview']['status']=='passed' and report['qa_preview']['checks']==['NAME']
        assert report['tests_run']==1
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    result=dict(passed=True,real_docker_jobs=len(jobs),real_chromium=True,unit_green_qa_conflict_rejected=True,
        code_only_fix_passes_same_frozen_contract=True,paid_calls=0,native_lifecycle=False,model_judgment=False,
        delivery_approval=False,all_owned_jobs_retired=True,product_driver_shadow_rejected=True,jobs=jobs,image=image)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    try:qualify(args.root.absolute(),args.image)
    except BaseException as error:
        write_json(args.root/'failure.json',dict(category=type(error).__name__,detail=str(error)[:2000],delivery_approval=False))
        raise
