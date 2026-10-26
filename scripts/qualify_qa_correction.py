"""Real Docker proof of the narrow, independently reviewed QA-text exception.

Controller decisions are scripted fixtures; no model, native lifecycle, GitHub
or autonomous-delivery claim. Historical Red stays historical, never regenerated.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_browser_preview import APP
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import Pending,write_json
from fabriquinha.executor import Runner,docker,seal_validation
from fabriquinha.quality import Quality,suite_report,CONTROL_CONTRACT
from fabriquinha.publication import Repository,LocalCI


def qualify(root,image,*,pinned=False):
    if root.exists():raise ValueError('fresh private proof root required')
    root.mkdir(mode=0o700,parents=True)
    project=Project.parse(dict(version=1,namespace='delivery-kit-qa-correction',repository='https://github.com/example/correction-proof',
        branch='release/proof',validation_image=image,browser_image=image,tests_dir='tests',qualification=True,browser_tdd=True,
        coordination_roles={'product':'product','lead':'lead'},delivery_roles={'tests':'qa','integration':'devops'},
        reviewers={'qa':'lead','author':'lead','lead':'cto','devops':'qa'}))
    store=Store(root/'private')
    if pinned:write_json(root/'installation.json',dict(project=project.fingerprint(),control_contract=CONTROL_CONTRACT,
        validation_bundle=seal_validation(store)))
    runner=Runner(project,store);work=root/'work';(work/'tests').mkdir(parents=True)
    (work/'app.py').write_text(APP.replace('DISPLAY','Nothing'))
    (work/'tests/test_existing.py').write_text('import unittest\nclass Existing(unittest.TestCase):\n def test_existing(self):self.assertTrue(True)\n')
    initial=store.capture(work)
    (work/'tests/test_feature.py').write_text('import unittest,app\nclass Feature(unittest.TestCase):\n def test_name(self):self.assertIn("Ana",app.PAGE)\n')
    check=dict(id='NAME',path='/',actions=[dict(action='click',selector='#show')],selector='#result',text='Ana')
    (work/'tests/qa.json').write_text(json.dumps(dict(version=1,checks=[check])))
    candidate=store.capture(work);inputs={};authority=[None]
    board=SimpleNamespace(ensure=lambda run:None,input=lambda run,name,**kw:inputs[name],criteria=lambda run:('NAME',),
        repair_input=lambda run:authority[0],review=lambda run,summary,evidence,**kwargs:inputs.update(evidence))
    quality=Quality(project,store,runner,board)
    def wait(call):
        until=time.monotonic()+project.timeout_seconds*3+45
        while True:
            try:return call()
            except Pending:
                if time.monotonic()>until:raise
                time.sleep(.1)
    # Exercise the actual CI entry point, not merely its underlying suite job.
    # Both the ordinary additive feature and the exceptional correction must work.
    remote=root/'remote.git';seed=root/'git-seed';remote.mkdir();store.checkout(initial,seed)
    def git(folder,*args):
        return subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false','-C',str(folder),*args],
                              check=True,capture_output=True,text=True).stdout.strip()
    git(remote,'init','--bare','--initial-branch=main');git(seed,'init','--initial-branch=main');git(seed,'add','.')
    git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','Isolated CI fixture')
    git(seed,'remote','add','origin',str(remote));git(seed,'push','origin','HEAD:refs/heads/'+project.branch)
    repository=Repository(project,store,remote=remote);base=repository.base();ci=LocalCI(project,store,repository,runner)
    normal=root/'normal-feature';store.checkout(candidate,normal);(normal/'app.py').write_text(APP.replace('DISPLAY','Ana'))
    feature=store.capture(normal);head=repository.propose(feature,base,'fixture/feature','fixture');repository.push('fixture/feature',head)
    normal_ci=wait(lambda:ci.validate(head,base,stage='proposal'))
    assert store.receipt(normal_ci)['payload']['conclusion']=='success'
    repository.push(project.branch,head)
    author=Run('old-tests',1,'qa','tests',False,'qa','proof','old-tests-contract')
    red=wait(lambda:quality.red(author,initial,candidate));inputs['red']=red
    verdict=dict(decision='approve',reason='Scripted independent fixture judgment; no autonomy claim.',findings=[])
    historical=quality.tests_review(replace(author,number=2,actor='lead',reviewing=True),red,verdict)
    (work/'app.py').write_text(APP.replace('DISPLAY','Hello, Ana!'))
    before=store.capture(work);old_files={p:p.read_bytes() for p in (work/'tests').iterdir()}
    # Actual unit Green and failed frozen browser preview, matching the incident.
    implementation=Run('old-implementation',3,'author','implementation',False,'author','proof','old-impl-contract')
    inputs['tests']=historical
    try:wait(lambda:quality.green(implementation,historical,before))
    except ValueError as error:assert 'preview' in str(error)
    else:raise AssertionError('contradictory QA unexpectedly passed')
    failure=quality.suite_refusal
    assert failure and not suite_report(store.receipt(failure)['payload'],diagnostic=True)['failures']
    diagnosis=Run('correction-diagnosis',4,'lead','diagnostic',False,'lead','proof','diagnosis-contract')
    diagnostic_job,negative=wait(lambda:quality.observe(diagnosis,before,'green'))
    assert negative['qa_preview']['status']=='failed' and not negative['failures']
    try:quality.green(diagnosis,historical,before)
    except ValueError:pass
    else:raise AssertionError('diagnostic acquired implementation authority')
    context=store.record('repair_context',dict(release='proof'),dict(project=project.fingerprint(),snapshot=before,
        tests=historical,qa_paths=['tests/qa.json'],failure_job=failure))
    body=dict(version=1,kind='plan',release='proof',repair_of='failed-integration',repair_context=context)
    planner=Run('repair-plan',4,'lead','plan',False,'lead','proof',digest(body))
    proposed=store.record('work_plan',planner.binding(),dict(project=project.fingerprint(),repair_body=body,
        document=dict(classification='test_contract',reason='Approved behavior contains the name; deterministic wording is a technical choice.',test_paths=['tests/qa.json'])))
    reviewer=replace(planner,number=5,actor='cto',reviewing=True)
    authority[0]=store.record('plan_review',reviewer.binding(),dict(project=project.fingerprint(),plan=proposed,verdict=verdict))
    (work/'tests/qa.json').write_text(json.dumps(dict(version=1,checks=[{**check,'text':'Hello, Ana!'}])))
    corrected=store.capture(work)
    current=Run('correction-tests',6,'qa','tests',False,'qa','proof','correction-contract')
    revision=wait(lambda:quality.red(current,before,corrected));inputs['red']=revision
    quality.handoff(current,'Scripted native-boundary handoff without lifecycle claim',{'red':revision})
    assert store.receipt(revision)['kind']=='test_revision'
    assert store.receipt(revision)['payload']['historical_red']==red
    frozen=quality.tests_review(replace(current,number=7,actor='lead',reviewing=True),revision,verdict);inputs['tests']=frozen
    try:quality.protect(before,corrected)
    except ValueError:pass
    else:raise AssertionError('ordinary work gained the correction exception')
    quality.protect(before,corrected,allow_revision=True)
    implementer=Run('correction-implementation',8,'author','implementation',False,'author','proof','correction-impl-contract')
    green=wait(lambda:quality.green(implementer,frozen,corrected));inputs['green']=green
    (work/'app.py').write_text(APP.replace('DISPLAY','Wrong'))
    mutant=store.capture(work)
    controls=wait(lambda:quality.controls(implementer,green,[mutant]));inputs['controls']=controls
    review=wait(lambda:quality.delivery_review(replace(implementer,number=9,actor='lead',reviewing=True),green,controls,verdict))
    # Seed the known contradictory old release as fixture input, without claiming
    # CI or delivery approval for it. Then qualify the reviewed correction by CI.
    bad_base=repository.propose(before,head,'fixture/contradiction','fixture');repository.push(project.branch,bad_base)
    fixed_head=repository.propose(corrected,bad_base,'fixture/correction','fixture');repository.push('fixture/correction',fixed_head)
    if pinned:
        checkout=root/'changed-checkout';folder=checkout/'src/fabriquinha';folder.mkdir(parents=True)
        for name in ('browser.py','suite.py'):(folder/name).write_text('raise RuntimeError("mutable checkout must not execute")\n')
        with patch('fabriquinha.executor.ROOT',checkout):correction_ci=wait(lambda:ci.validate(fixed_head,bad_base,stage='proposal'))
    else:correction_ci=wait(lambda:ci.validate(fixed_head,bad_base,stage='proposal'))
    ci_data=store.receipt(correction_ci)['payload'];job=store.receipt(ci_data['job'])['payload']
    integrated=(ci_data['job'],suite_report(job));assert ci_data['conclusion']=='success'
    assert integrated[1]['qa_preview']['status']=='passed'
    assert (store.tree(before)/'app.py').read_bytes()==(store.tree(corrected)/'app.py').read_bytes()
    assert all(p.name=='qa.json' or p.read_bytes()==content for p,content in old_files.items())
    assert store.receipt(historical)['payload']['red']==red
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    jobs=[p for p in (store.root/'receipts').glob('*.json') if store.receipt(p.stem)['kind']=='suite_job']
    result=dict(passed=True,real_docker_jobs=len(jobs),historical_red=red,test_revision=revision,freeze=frozen,
        delivery_review=review,unit_green_conflicting_qa_rejected=True,ordinary_exception_denied=True,
        diagnostic_browser_failure_visible_without_approval=True,diagnostic_job=diagnostic_job,
        pinned_validation=pinned,changed_checkout_ignored=pinned,
        normal_additive_ci_passed=True,reviewed_correction_ci_passed=True,normal_ci=normal_ci,correction_ci=correction_ci,
        existing_unit_tests_unchanged=True,product_unchanged=True,controls_preserved=True,integrated_browser_passed=True,
        paid_calls=0,model_judgment=False,native_lifecycle=False,delivery_approval=False,all_jobs_retired=True)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--image',required=True)
    parser.add_argument('--pinned',action='store_true')
    args=parser.parse_args();qualify(args.root.absolute(),args.image,pinned=args.pinned)
