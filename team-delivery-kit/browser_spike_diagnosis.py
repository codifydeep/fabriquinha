"""One CTO diagnosis and independent review of a fixed, completed causal SPIKE."""
import argparse
import hashlib
import json
from pathlib import Path

import browser_evidence_trial as trial
from evalctl import PRIVATE,PROJECT
from prepare_issue_base import broker_post
from qa_postmerge_trial import write_once
from start_eval import cli,read_model_budget

LABEL='BROWSERSPIKE-1'
FOLDER=PRIVATE/'browser-diagnosis-trial'/LABEL


def start():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated spike diagnosis only')
    if (FOLDER/'launch.json').exists():return json.loads((FOLDER/'launch.json').read_text())
    if read_model_budget()['remaining']<48:raise ValueError('insufficient bounded diagnosis/review budget')
    previous=json.loads((PRIVATE/'browser-diagnosis-trial/BROWSERDIAG-3/review-result.json').read_text())
    if previous['stage']!='blocked_invalid_diagnosis' or previous['reads']['status']!='read_evidence_verified':
        raise ValueError('verified prior technical blockage required')
    original=json.loads((PRIVATE/'browser-diagnosis-trial/BROWSERDIAG-3/launch.json').read_text())
    launch={'runtime_spike_receipt':str(PRIVATE/'browser-runtime-spike/result.json')}
    capsule=trial.spike_capsule(launch)
    receipt=capsule['receipt']
    if receipt['status']!='causal_spike_passed' or receipt['cleanup']!='passed':
        raise ValueError('completed causal experiment required')
    role=json.loads((PRIVATE/'planning-agents.json').read_text())['agents']['cto']
    title=LABEL+' — CTO diagnosis from executed causal SPIKE'
    prompt=('Historical diagnosis-only CTO SPIKE, NOT product implementation, release or '
            'permission to restart an old parent. Read all bound artifacts: qa.json, scenario.py, '
            'spike.json, probe.py and actual app.js/index.html. The controller executed a '
            'baseline and an explicitly in-memory intervention in isolated Chromium. '
            'Explain causality using OBSERVED runtime types, field names, error stack and '
            'the intervention result. Do not invent missing fields, a timing race, or source '
            'drift contradicted by verified hashes. Return only the five-field QA JSON '
            '(decision,root_cause,editable_code_files,new_test_file,acceptance). '
            'Use repository-relative paths and a NEW tests/test_*.py Python unittest. '
            'root_cause <=1000 chars, acceptance <=5 strings each <=300 chars. '
            'For blocked use empty code/test paths and acceptance; for repair give a complete '
            'regression recommendation for HISTORICAL SHA only, never current main. '
            'The in-memory intervention is NOT a product fix or TDD receipt. No terminal, '
            'Python execution, writes, tests, merge, administration or homologation claims. '
            'QA_DIAGNOSIS_V1 Read artifacts in consecutive60-line pages through EOF.')
    matches=[v for v in cli('search',title,'--include-closed','--limit','100')['issues'] if v['title']==title]
    if len(matches)>1:raise ValueError('duplicate bounded spike diagnosis')
    card=matches[0] if matches else cli('create','--title',title,'--description',prompt,
        '--status','todo','--parent',previous['issue_id'])
    if card.get('parent_issue_id')!=previous['issue_id'] or card.get('assignee_id') not in (None,role):
        raise ValueError('spike handoff drift')
    if card.get('assignee_id') is None:cli('assign',card['id'],'--to-id',role,'--no-start')
    delivery=json.loads((PRIVATE/'release-receipts/SUMB-2.json').read_text())
    failed=json.loads(Path(original['receipt']).read_text())
    data=trial.payload(delivery,failed,card['id'],role,capsule)
    if len(json.dumps(data).encode())>16384:raise ValueError('bounded artifact request exceeded')
    broker_post('/v1/qa-diagnostic-artifacts',data)
    intent={**launch,'label':LABEL,'issue_id':card['id'],'agent_id':role,
        'source_sha':trial.SOURCE,'receipt':original['receipt'],'stage':'spike_registered',
        'scope':'diagnosis_only_historical_no_repair','budget_at_start':read_model_budget(),
        'spike_sha256':hashlib.sha256(json.dumps(receipt,sort_keys=True).encode()).hexdigest()}
    write_once(FOLDER/'intent.json',intent)
    runs=cli('runs',card['id'])
    if any(r.get('agent_id')!=role for r in runs):raise ValueError('foreign spike diagnostic run')
    if not runs:cli('rerun',card['id'])
    value={**intent,'stage':'spike_diagnosis_started'}
    write_once(FOLDER/'launch.json',value)
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('start','check','review','check-review','review-contract','check-contract'))
    action=parser.parse_args().action
    trial.LABEL=LABEL;trial.FOLDER=FOLDER
    actions={'start':start,'check':trial.check,'review':trial.review,'check-review':trial.check_review,
             'review-contract':lambda:trial.review(contract_retry=True),
             'check-contract':lambda:trial.check_review(contract_retry=True)}
    print(json.dumps(actions[action]()))
