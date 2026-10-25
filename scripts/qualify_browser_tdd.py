"""Qualify browser Red/Green with a counter, not product code or model judgment.

No native lifecycle claim: scripted independent freeze, real Docker/Chromium,
unchanged tests, and a decoy mutation retaining the expected source tokens.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
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
from fabriquinha.quality import Quality


def qualify(root,image):
    if root.exists():raise ValueError('fresh private qualification root required')
    root.mkdir(mode=0o700,parents=True)
    project=Project.parse(dict(version=1,namespace='delivery-kit-browser-tdd',
        repository='https://github.com/example/browser-qualification',branch='release/proof',
        validation_image=image,tests_dir='tests',reviewers={'author':'reviewer'},qualification=True,browser_tdd=True))
    store=Store(root/'private');runner=Runner(project,store);inputs={}
    quality=Quality(project,store,runner,SimpleNamespace(ensure=lambda run:None,input=lambda run,key,**kw:inputs[key]))
    fixtures=ROOT/'tests/fixtures/browser_tdd';baseline=store.capture(fixtures/'base')
    work=root/'work';store.checkout(baseline,work)
    shutil.copyfile(fixtures/'test_counter.py',work/'tests/test_counter.py')
    run=Run('tests',1,'author','tests',False,'author','qualification','contract')
    def wait(operation):
        deadline=time.monotonic()+project.timeout_seconds+15
        while True:
            try:return operation()
            except Pending:
                if time.monotonic()>=deadline:raise
                time.sleep(0.1)
    red=wait(lambda:quality.red(run,baseline,store.capture(work)))
    inputs['red']=red
    reviewer=replace(run,number=2,actor='reviewer',reviewing=True)
    frozen=quality.tests_review(reviewer,red,dict(decision='approve',reason='Scripted isolation and browser capability proof only.',findings=[]))
    inputs['tests']=frozen
    # Change only the fixture product; frozen tests stay byte-identical.
    original=(work/'app.py').read_text()
    green_html='''<script>let value=0;document.querySelector('#increment').addEventListener('click',()=>{document.querySelector('#count').textContent=String(++value);});</script>'''
    # Use repr to keep Python quoting independent of JavaScript string quotes.
    page=b'<!doctype html><button id="increment" type="button">Increment</button><output id="count">0</output>'
    def app(script):
        lines=original.splitlines()
        return '\n'.join('PAGE = '+repr(page+script.encode()) if line.startswith('PAGE = ') else line for line in lines)+'\n'
    (work/'app.py').write_text(app(green_html))
    implementation=Run('implementation',3,'author','implementation',False,'author','qualification','contract')
    green=wait(lambda:quality.green(implementation,frozen,store.capture(work)))
    mutant=root/'mutant';store.checkout(store.capture(work),mutant)
    (mutant/'app.py').write_text(app("<script>/* Same source tokens: addEventListener, textContent, String(++value). No behavior. */</script>"))
    control=wait(lambda:quality.controls(implementation,green,[store.capture(mutant)]))
    frozen_data=store.receipt(frozen)['payload'];red_data=store.receipt(red)['payload']
    assert frozen_data['new_cases']==['test_counter.CounterBehavior.test_click_changes_dom_not_just_source_tokens']
    jobs=[red_data['baseline_job'],red_data['red_job'],store.receipt(green)['payload']['job'],*store.receipt(control)['payload']['jobs']]
    assert len(jobs)==4
    for key in jobs:
        assert store.receipt(key,kind='suite_job')['payload']['sandbox']==dict(network='none',snapshot='readonly',user='65534:65534')
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    result=dict(passed=True,real_chromium=True,real_docker_jobs=len(jobs),assertion_based_red=True,
        same_frozen_tests_green=True,source_token_decoy_rejected=True,credential_and_delivery_write_denied=True,
        scripted_review=True,native_lifecycle=False,model_judgment=False,paid_calls=0,delivery_approval=False,
        all_owned_jobs_retired=True,image=image)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    try:qualify(args.root.resolve(),args.image)
    except BaseException as error:
        write_json(args.root/'failure.json',dict(category=type(error).__name__,message=str(error)[:2000],delivery_approval=False));raise
