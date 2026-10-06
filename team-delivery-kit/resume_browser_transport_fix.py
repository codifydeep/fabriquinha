"""One operator-only resumption after a verified transport infrastructure fix."""
import hashlib
import json

from evalctl import PRIVATE, PROJECT
from controller_broker_image import installed_image
from portable_delivery import managed_handoff
from release_eval import save_receipt
from start_eval import cli, check_model_budget

ISSUE = '01a0f44d-fc5d-75be-8a8f-ab806b0d49c2'
SOURCE = '01a0f458-4728-7c5c-90e9-a386d167f463'
AUTHOR = 'ce91fe5b-f6dd-4798-8f8c-6d3618ea83a1'
IMAGE = 'sha256:31a62635306f2b19dd54fafb7d00fad55ee113f71147db66a56b6827ea690825'


def main():
    if PROJECT != 'delivery-kit-port2' or installed_image(PROJECT) != IMAGE:
        raise ValueError('transport fix installation identity mismatch')
    marker = 'DELIVERY_HANDOFF ' + hashlib.sha256((ISSUE + ':' + SOURCE + ':transport-idle-total-fix').encode()).hexdigest()
    wakeups = [w for w in cli('wakeup', 'list', ISSUE)
               if w.get('instruction', '').startswith(marker)]
    if len(wakeups) > 1:
        raise ValueError('duplicate transport fix wakeups')
    if wakeups:
        print(json.dumps({'stage': 'already_registered', 'wakeup_id': wakeups[0]['id']}))
        return
    runs = cli('runs', ISSUE)
    source = next((r for r in runs if r['id'] == SOURCE), None)
    if (not source or source.get('agent_id') != AUTHOR or source.get('status') != 'failed'
            or 'prompt_timeout' not in (source.get('error') or '')
            or any(r['status'] in ('running', 'queued') for r in runs)):
        raise ValueError('exact transport failure or idle task state not confirmed')
    managed = managed_handoff({'issue_id': ISSUE})
    if not managed or managed['state']['stage'] != 'test_first_blocked':
        raise ValueError('original tests-only incident must remain preserved and blocked')
    budget = check_model_budget()
    instruction = (
        marker + '\nCONTROLLER VERIFIED INFRASTRUCTURE CORRECTION: prior source '
        + SOURCE + ' failed with prompt_timeout, not a failed regression assertion. '
        'Broker .57 now distinguishes 300 seconds of inactivity from a finite '
        '1800-second total prompt limit. This is ONE resumption of the SAME card, '
        'not an identical retry or permission to weaken the contract. PHASE 1 '
        'TESTS ONLY. Write tests/test_browser_feedback_flow.py using the file '
        'tool; do not edit product code or old tests. The task description remains '
        'the behavioral acceptance. Node experiments belong INSIDE that declared '
        'unittest, executed by the full pinned suite; no ad-hoc node -e, /tmp '
        'writes, root/session-state searches, or attempts to find controller files. '
        'Read product files only in /workspace. Run exactly: cd /workspace && '
        'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
        'Controller must independently capture genuine Red. Preserve all tests, '
        'review independence, snapshots, model counter and paid-call ceiling.')
    wakeup = cli('wakeup', 'create', ISSUE, '--agent-id', AUTHOR,
                 '--event', 'task.failed', '--task-id', SOURCE, '--mode', 'once',
                 '--instruction', instruction)
    receipt = {'issue_id': ISSUE, 'source_task': SOURCE, 'image': IMAGE,
               'wakeup_id': wakeup['id'], 'model_calls_before': budget['calls'],
               'stage': 'transport_fix_registered_not_approved'}
    save_receipt(PRIVATE / 'browser-transport-resume.json', receipt)
    cli('metadata', 'set', ISSUE, '--key', 'transport_fix_wakeup',
        '--value', wakeup['id'], '--type', 'string')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
