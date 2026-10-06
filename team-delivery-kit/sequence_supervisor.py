"""Restart a crashed dependent sequence; stop on delivery or a visible incident.

The child owns the sequence lock. A supervisor restart may safely wait for an
older child to finish before reconciling the durable ledger.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from dependent_sequence import load_plan, read_json
from release_eval import save_receipt


ROOT = Path(__file__).resolve().parent
MAX_CRASHES = 2


def supervise(ledger_path, run, *, maximum=MAX_CRASHES, reconcile_blocked=False):
    """Run until done, blocked, or repeated controller crashes are recorded."""
    ledger_path = Path(ledger_path)
    while True:
        ledger = read_json(ledger_path) or {}
        if ledger.get('stage') == 'done':
            # Re-enter the child once to verify the completed receipt against
            # GitHub, board and live QA, not just the local ledger flag.
            return 0 if run() == 0 else 1
        if ledger.get('stage') == 'blocked' and not reconcile_blocked:
            return 1
        result = run()
        ledger = read_json(ledger_path) or {}
        if ledger.get('stage') == 'done':
            return 0 if result == 0 else 1
        if ledger.get('stage') == 'blocked':
            return 1
        crashes = ledger.get('controller_crashes', 0) + 1
        ledger.update(controller_crashes=crashes, updated_at=time.time())
        if crashes >= maximum:
            ledger.update(stage='blocked', owner='techlead',
                          category='controller_exited_without_terminal_state',
                          next_action='Inspect child exit, board and receipts; diagnose before resuming',
                          last_exit_code=result)
        save_receipt(ledger_path, ledger)
        if ledger['stage'] == 'blocked':
            return 1


def main():
    selected = os.environ.get('DELIVERY_KIT_SEQUENCE_PLAN')
    if not selected:
        raise ValueError('DELIVERY_KIT_SEQUENCE_PLAN required')
    plan = load_plan(selected)
    from evalctl import PRIVATE, PROJECT
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('sequence supervisor restricted to isolated port2 installation')
    ledger_path = PRIVATE / 'dependent-sequences' / (plan['name'] + '.json')
    def run():
        return subprocess.run([sys.executable, str(ROOT / 'dependent_sequence.py')],
                              cwd=ROOT, env=os.environ.copy(), check=False).returncode
    # Child holds the sequence lock and may resolve a blocked stage ONLY from a
    # fully verified recovery receipt. It never blindly reruns a failed author.
    result = supervise(ledger_path, run, reconcile_blocked=True)
    ledger = read_json(ledger_path) or {}
    health = None
    if result == 0 and ledger.get('stage') == 'done':
        from portable_qualification import verify_docker_deployment
        last = plan['stages'][-1]
        from dependent_sequence import read_stage_delivery
        receipt = read_stage_delivery(PRIVATE, last)
        try:
            deployment = receipt['deployment']
            verify_docker_deployment(deployment['container'], deployment['url'],
                                     receipt['merge_sha'], last['contract'])
            health = {'status': 'healthy', 'source_sha': receipt['merge_sha'],
                      'url': deployment['url'], 'checked_at': time.time()}
        except Exception as error:
            health = {'status': 'deployment_unavailable', 'owner': 'devops',
                      'category': (type(error).__name__ + ':' + str(error))[:160],
                      'next_action': 'Restore the exact-SHA local deployment and rerun QA',
                      'checked_at': time.time()}
            result = 1
        save_receipt(PRIVATE / 'dependent-sequences' /
                     (plan['name'] + '.health.json'), health)
    print(json.dumps({'sequence': plan['name'], 'stage': ledger.get('stage'),
                      'completed': ledger.get('completed', []),
                      'controller_crashes': ledger.get('controller_crashes', 0),
                      'category': ledger.get('category'), 'health': health}), flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
