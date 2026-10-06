"""Fresh tests-first increment; historical diagnosis is never a repair base."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys

from evalctl import PRIVATE, PROJECT
from portable_contract import is_test_path, validate
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import write_once
from start_eval import read_model_budget

ROOT=Path(__file__).resolve().parent
BASE='cdb81c0ac62eea08a551cd97ef4dd9e8bd2a2cf0'
LABEL='SORT-1'
NEW_TEST='tests/test_feedback_sort_client.py'


def derive(template,tracked):
    existing=set(tracked)
    code={'app/static/app.js','app/static/index.html'}
    if NEW_TEST in existing or not code|{'tests/test_feedback_filter_client.py'} <= existing:
        raise ValueError('sort baseline drift')
    tests={p for p in existing if any(is_test_path(p,r,'python3') for r in template['test_roots'])}
    editable=code|{NEW_TEST};files=existing|{NEW_TEST}
    contract={**template,'files':sorted(files),'required_files':sorted(files),
              'editable_files':sorted(editable),'protected_files':sorted(existing-code),
              'test_files':sorted(tests|{NEW_TEST})}
    validate(contract)
    description=(
        'Fresh qualification on CURRENT disposable feedback board, not historical repair. '
        'Add a native select with accessible name Sort feedback and options Newest first '
        '(first option, default) and Oldest first. Sort by numeric feedback ID descending '
        'or ascending, independently in each page. ID is stable creation order; do not '
        'use timestamps, array order, string sort, URL or storage. Selection survives '
        'polling, filter changes, creation and completion. Preserve drafts, pending-submit '
        'protection, keyboard/Escape behavior, filters, whole-board summary and all existing '
        'tests byte-for-byte. No API change. Do not mutate fetched input arrays. '
        'PHASE 1 TESTS ONLY: create '+NEW_TEST+'. Use Python unittest executing actual '
        'app.js through installed Node and a faithful minimal DOM/VM harness. Inspect the '
        'existing filter and browser-flow tests for conventions without editing them. '
        'Cover default, both numeric directions (IDs 2 and 10), independence, filter '
        'composition, poll/create/complete persistence and preserved drafts. Exercise '
        'real registered events and fetched data, not replacement application logic or '
        'source regex alone. No skips, swallowed errors, sleeps or unsupported dependencies. '
        'Keep the new test <=32768 UTF-8 bytes with one reusable harness. Controller '
        'captures Red and independent immutable test review before implementation. '
        'PHASE 2: edit only app/static/app.js and app/static/index.html to satisfy frozen '
        'tests. Preserve approved tests; do not recreate Red. Full command: cd /workspace '
        '&& PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
        'No GitHub, Docker, network, credentials or other projects in workers. '
        'Completion requires independent delivery review, CI, deployment and real-browser QA.')
    spec={'label':LABEL,'title':LABEL+' — independent newest/oldest feedback views',
          'description':description,
          'review_instruction':'Review frozen /delivery only. Require genuine controller Red, independent test approval, Green/full suite and unchanged old tests. Inspect actual numeric ID ordering including 2/10, both directions, independent page state, filtering, poll/create/complete persistence and preserved drafts. Reject replacement logic, text-only tests, skips or blanket bans on valid lexical browser bindings. Never edit or replay Red. Run controlled full suite. Browser QA and CI remain mandatory controller gates. Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>.',
          'qa_host_port':19446,'container_port':8080,'dockerfile':'Dockerfile.feedback-bootstrap',
          'implementer_registry':'pilot-frontend.json','reviewer_registry':'pilot-techlead-reviewer.json',
          'runtime_env':{'FEEDBACK_DB_PATH':'/tmp/feedback.db'},
          'browser_qa':{'scenario':'feedback-board-sort-v1',
              'browser_image':'sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b'}}
    validate_spec(spec,contract)
    return contract,spec


def prepare():
    project=current();budget=read_model_budget()
    if PROJECT!='delivery-kit-port2' or project['repository']!='codifydeep/descartavel2':
        raise ValueError('isolated disposable project required')
    if budget['remaining']<128:raise ValueError('full cycle requires128 available calls')
    if verified_main()!=BASE:raise ValueError('current main changed; replan required')
    tracked=subprocess.check_output(['git','-C',str(project['checkout']),
        'ls-tree','-r','--name-only',BASE],text=True).splitlines()
    template=json.loads((ROOT/'projects/descartavel2-filter-1-ui.contract.json').read_text())
    contract,spec=derive(template,tracked)
    write_once(ROOT/'projects/descartavel2-sort-1.contract.json',contract)
    write_once(ROOT/'projects/descartavel2-sort-1.run.json',spec)
    value={'label':LABEL,'base_sha':BASE,'stage':'prepared_not_dispatched','budget':budget}
    intake=PRIVATE/'sort-1-intake.json'
    if intake.exists():
        prior=json.loads(intake.read_text())
        if prior.get('base_sha')!=BASE or prior.get('label')!=LABEL:raise ValueError('intake drift')
        return prior
    write_once(intake,value)
    return value


def controls():
    from portable_browser_qa import qualify
    folder=PRIVATE/'sort-1-controls'
    config={'scenario':'feedback-board-filter-v1',
        'browser_image':'sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b'}
    kwargs={'deployed_container':'delivery-kit-port2-testrevddea64bf8698-1-qa',
        'source_sha':BASE,'runtime_env':{'FEEDBACK_DB_PATH':'/tmp/feedback.db'}}
    positive=qualify(config=config,evidence_dir=folder/'baseline-regression',**kwargs)
    if positive['status']!='passed' or positive['cleanup']!='passed':
        raise ValueError('unchanged regression browser control failed')
    negative_folder=folder/'feature-absent'
    prior=list(negative_folder.glob('*.json'))
    if not prior:
        try:
            negative=qualify(config={**config,'scenario':'feedback-board-sort-v1'},
                evidence_dir=negative_folder,**kwargs)
        except ValueError:
            prior=list(negative_folder.glob('*.json'))
            if len(prior)!=1:raise
            negative=json.loads(prior[0].read_text())
    elif len(prior)==1 and not prior[0].is_symlink():
        negative=json.loads(prior[0].read_text())
    else:raise ValueError('ambiguous negative control; do not retry')
    if (negative['status']!='failed' or negative['cleanup']!='passed'
            or 'Sort feedback' not in negative.get('error','')):
        raise ValueError('baseline must fail specifically on absent sort control')
    expected={**positive['identity'],'config':{**config,'scenario':'feedback-board-sort-v1'}}
    if negative.get('identity')!=expected or negative.get('automated') is not True:
        raise ValueError('negative control identity drift')
    value={'label':LABEL,'base_sha':BASE,'stage':'controls_verified_not_tdd',
        'positive':positive,'negative':negative}
    write_once(folder/'result.json',value)
    return {'label':LABEL,'stage':value['stage']}


def start():
    folder=PRIVATE/'portable-supervisor';launch=folder/(LABEL+'.launch.json')
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated launch required')
    if launch.exists():return json.loads(launch.read_text())
    prepare()
    proof=json.loads((PRIVATE/'sort-1-controls/result.json').read_text())
    from portable_browser_qa import SCRIPT
    import hashlib
    if (proof.get('stage')!='controls_verified_not_tdd' or proof.get('base_sha')!=BASE
            or any(v['identity']['scenario_sha256']!=hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
                   for v in (proof['positive'],proof['negative']))):
        raise ValueError('current verified browser controls required')
    intent=folder/(LABEL+'.intent.json')
    if intent.exists():raise ValueError('interrupted launch requires reconciliation, not duplicate dispatch')
    folder.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'DELIVERY_KIT_DELIVERY_CONTRACT':str(ROOT/'projects/descartavel2-sort-1.contract.json'),
         'DELIVERY_KIT_RUN_SPEC':str(ROOT/'projects/descartavel2-sort-1.run.json'),
         'DELIVERY_KIT_TEST_FIRST':'1'}
    write_once(intent,{'label':LABEL,'base_sha':BASE,'stage':'launch_intent'})
    subprocess.run([sys.executable,str(ROOT/'start_portable.py')],env=env,check=True)
    log=folder/(LABEL+'.log')
    with log.open('ab') as output:
        worker=subprocess.Popen([sys.executable,str(ROOT/'portable_supervisor.py'),'--managed-label',LABEL],
            cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    value={'label':LABEL,'base_sha':BASE,'stage':'supervisor_started_not_delivered',
        'pid':worker.pid,'log':str(log),'budget':read_model_budget()}
    write_once(launch,value)
    return value


def check():
    path=PRIVATE/'autonomy-status'/('SORT-1.json')
    return {'budget':read_model_budget(),'status':json.loads(path.read_text()) if path.exists() else None}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','controls','start','check'))
    action=parser.parse_args().action
    print(json.dumps({'prepare':prepare,'controls':controls,'start':start,'check':check}[action]()))
