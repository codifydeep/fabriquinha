"""Real isolated Chromium proof; synthetic fixtures only, never product delivery."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import Pending,write_json
from fabriquinha.executor import Runner,seal_validation
from fabriquinha.quality import CONTROL_CONTRACT,suite_report
from fabriquinha.observer_maintenance import snapshot_diff
from fabriquinha.maintenance import observer_failures

APP='''import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
BAD=False
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
  if self.path=='/favicon.ico':return
  if self.path in ('/health','/identity'):
   self.wfile.write(json.dumps({'status':'ok'} if self.path=='/health' else {'source_sha':os.environ.get('FABRIQUINHA_SOURCE_SHA')}).encode());return
  self.wfile.write(("<link rel='icon' href='data:,'><button id='trigger'>Trigger</button><script>document.querySelector('button').onclick=()=>{" + ("console.error('maintenance-late-error')" if BAD else "document.title='ok'") + "}</script>").encode())
 def log_message(self,*args):pass
if __name__=='__main__':HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
'''
OLD='''from fabriquinha_acceptance import AcceptanceTest
class Observer(AcceptanceTest):
    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(self.target)
        return page, errors
    def full_room_pair(self):
        creator_page, creator_errors = self.open_home()
        joiner_page, joiner_errors = self.open_home()
        return {'pages': [creator_page, joiner_page], 'errors': creator_errors + joiner_errors}
    def test_late(self):
        pair = self.full_room_pair()
        for page in pair['pages']:
            page.get_by_role('button', name='Trigger').click()
            page.evaluate('() => new Promise(resolve => setTimeout(resolve, 30))')
        self.assertEqual(pair['errors'], [])
'''


def qualify(root,image,browser):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(parents=True,mode=0o700)
    project=Project.parse(dict(version=1,namespace='delivery-kit-observer-proof',repository='https://github.com/example/proof',
        branch='release/proof',validation_image=image,browser_image=browser,browser_tdd=True,tests_dir='tests',
        reviewers={'qa':'lead','lead':'cto','devops':'qa'},coordination_roles={'product':'qa','lead':'lead'},
        delivery_roles={'tests':'qa','integration':'devops'},qualification=True))
    store=Store(root/'private');bundle=seal_validation(store)
    write_json(root/'installation.json',dict(project=project.fingerprint(),control_contract=CONTROL_CONTRACT,
        validation_bundle=bundle,browser_contract=2))
    work=root/'work';(work/'tests').mkdir(parents=True)
    (work/'app.py').write_text(APP)
    path='tests/acceptance_observer.py';(work/path).write_text(OLD)
    (work/'tests/test_unit.py').write_text('import unittest\nclass Unit(unittest.TestCase):\n def test_auxiliary(self):self.assertEqual(2+2,4)\n')
    write_json(work/'tests/acceptance.observer.json',dict(version=2,criteria={'OBSERVER':dict(cases=['acceptance_observer.Observer.test_late'],gates=[])}))
    original=store.capture(work)
    new=OLD.replace('errors = []','errors = self._browser_errors').replace("        page.on('pageerror', lambda error: errors.append(str(error)))\n",'').replace("        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)\n",'').replace('creator_errors + joiner_errors','self._browser_errors')
    (work/path).write_text(new);candidate=store.capture(work)
    snapshot_diff(store,original,candidate,[path])
    (work/'app.py').write_text(APP.replace('BAD=False','BAD=True'));negative=store.capture(work)
    (work/path).write_text(OLD);old_negative=store.capture(work)
    runner=Runner(project,store);run=Run('observer-proof',1,'qa','tests',False,'qa','proof','proof');jobs=[]
    def execute(snapshot,phase):
        deadline=time.monotonic()+project.timeout_seconds+30
        while True:
            try:key=runner.run(run,snapshot,phase);break
            except Pending:
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        jobs.append(key);return store.receipt(key,kind='suite_job')['payload']
    for snapshot in (original,candidate):
        value=execute(snapshot,'green');assert not suite_report(value)['failures']
    old=execute(old_negative,'control')
    assert old['report']['qa_preview']['status']=='failed' and not old['report']['failures']
    try:suite_report(old)
    except ValueError:pass
    else:raise AssertionError('central browser gate was bypassed')
    fixed=execute(negative,'control');report=suite_report(fixed)
    assert observer_failures(store,candidate,[path],report)=={path}
    assert report['tests_run']==2 and not report['errors'] and not report['skips']
    result=dict(passed=True,real_chromium=True,model_calls=0,scripted_fixture=True,delivery_approval=False,
        source_preserved=True,central_gate_preserved=True,late_error_after_two_context_setup=True,jobs=jobs)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--image',required=True);p.add_argument('--browser-image',required=True);a=p.parse_args()
    print(json.dumps(qualify(a.root.absolute(),a.image,a.browser_image),indent=2))
