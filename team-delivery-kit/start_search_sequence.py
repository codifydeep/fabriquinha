"""One-shot launch of the pinned isolated SEARCH-1 sequence supervisor."""
import json
import os
from pathlib import Path
import subprocess
import sys

from evalctl import PRIVATE, PROJECT, verify
from dependent_sequence import load_plan
from release_eval import save_receipt
from start_eval import read_model_budget

ROOT = Path(__file__).resolve().parent


def main():
    if PROJECT != 'delivery-kit-port2' or verify():
        raise ValueError('isolated healthy control plane required')
    plan_path = ROOT / 'projects/descartavel2-search-1.sequence.json'
    plan = load_plan(plan_path)
    launch = PRIVATE / 'dependent-sequences' / 'SEARCH-1-DELIVERY.launch.json'
    prior = json.loads(launch.read_text()) if launch.exists() else None
    if prior:
        if prior.get('plan_sha256') != plan['sha256']:
            raise ValueError('existing launch plan drift')
        status = subprocess.run(['ps', '-p', str(prior.get('pid') or 0), '-o', 'command='],
                                capture_output=True, text=True)
        if status.returncode == 0 and str(ROOT / 'sequence_supervisor.py') in status.stdout:
            print(json.dumps({'stage': 'supervisor_already_running', 'pid': prior['pid']}))
            return
    budget = read_model_budget()
    if not prior and budget['remaining'] < 192:
        raise ValueError('new two-card trial requires192remaining calls')
    if prior and budget['remaining'] < 32:
        raise ValueError('budget insufficient to reconcile and dispatch successor')
    env = {**os.environ, 'DELIVERY_KIT_SEQUENCE_PLAN': str(plan_path),
           'DELIVERY_KIT_TEST_FIRST': '1'}
    for key in ('DELIVERY_KIT_RUN_SPEC', 'DELIVERY_KIT_EXISTING_ISSUE_ID',
                'DELIVERY_KIT_TEST_REVISION_PARENT', 'DELIVERY_KIT_TEST_REVISION_DEPTH'):
        env.pop(key, None)
    launch.parent.mkdir(parents=True, exist_ok=True)
    intent = {'stage': 'launch_intent', 'sequence': plan['name'],
              'plan_sha256': plan['sha256'], 'remaining_calls': budget['remaining']}
    if prior:
        intent['prior_launch'] = prior
        intent['mode'] = 'evidence_verified_reconciliation_not_new_sequence'
    save_receipt(launch, intent)
    with (launch.parent / 'SEARCH-1-DELIVERY.log').open('a') as log:
        worker = subprocess.Popen([sys.executable, '-u', str(ROOT / 'sequence_supervisor.py')],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True)
    intent.update(stage='supervisor_started', pid=worker.pid)
    save_receipt(launch, intent)
    print(json.dumps(intent))


if __name__ == '__main__':
    main()
