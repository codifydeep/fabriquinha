"""One fresh-session implementation retry; accepted Red remains immutable."""
import hashlib
import fcntl
import json
import os
import subprocess
import time

from dependent_sequence import load_plan, read_json, verify_predecessor
from evalctl import PRIVATE, PROJECT
from portable_delivery import managed_handoff
from prepare_issue_base import broker_post
from release_eval import save_receipt
from start_eval import check_model_budget, cli

ISSUE = '01a0f87f-bef9-739b-b889-8d5b49ee988f'
SOURCE = '01a0f8b7-f792-7b82-9485-74449239eae8'
AUTHOR = 'ce91fe5b-f6dd-4798-8f8c-6d3618ea83a1'
RED_MANIFEST = 'e4ec1a46b809c17ed432d6934cad4586978dad0651c2cc618b8985997da18fe4'
TEST_HASH = '41f568c7017557a8749f89f9fb57c27ed97a0d53bb93405c99f240a6115365b5'


def resume():
    plan = load_plan(os.environ['DELIVERY_KIT_SEQUENCE_PLAN'])
    if PROJECT != 'delivery-kit-port2' or plan['name'] != 'FILTER-1-DELIVERY':
        raise ValueError('isolated context incident required')
    previous = read_json(PRIVATE / 'filter-context-recovery.json')
    if previous and previous.get('stage') == 'supervisor_resumable':
        if previous.get('source_task') != SOURCE or previous.get('red_manifest') != RED_MANIFEST:
            raise ValueError('context recovery identity drift')
        print(json.dumps({'stage': 'already_resumed', 'task_id': previous['task_id']}))
        return
    proxy = json.loads(subprocess.check_output(['docker', 'inspect', PROJECT + '-execution-broker-1'], text=True))[0]
    if not proxy['State']['Running'] or proxy['Config']['Image'] != 'delivery-kit-eval-broker:20261001.25':
        raise ValueError('task-scoped session fix not installed')
    ledger_path = PRIVATE / 'dependent-sequences' / (plan['name'] + '.json')
    ledger = read_json(ledger_path)
    if not ledger or ledger.get('plan_sha256') != plan['sha256'] or ledger.get('completed') != ['FILTERAPI-1']:
        raise ValueError('sequence predecessor identity drift')
    if check_model_budget()['remaining'] < 64:
        raise ValueError('64 reserved calls required')
    marker = 'DELIVERY_HANDOFF ' + hashlib.sha256((ISSUE + ':' + SOURCE + ':task-session-v1').encode()).hexdigest()
    wakeups = [w for w in cli('wakeup', 'list', ISSUE) if w.get('instruction', '').startswith(marker)]
    if len(wakeups) > 1:
        raise ValueError('duplicate context repair')
    managed = managed_handoff({'issue_id': ISSUE})
    route = dict(managed['route'])
    if not wakeups:
        runs = cli('runs', ISSUE)
        authors = [r for r in runs if r.get('agent_id') == AUTHOR]
        source = max(authors, key=lambda r: (r.get('created_at') or '', r['id']))
        output = (source.get('result') or {}).get('output', '')
        if (source['id'] != SOURCE or source['status'] != 'completed'
                or 'Context length exceeded (' not in output or 'Cannot compress further.' not in output
                or any(r['status'] in ('running', 'queued') for r in runs) or route['enabled']):
            raise ValueError('exact exhausted source and paused idle route required')
        verify_predecessor(read_json(PRIVATE / 'release-receipts' / 'FILTERAPI-1.json'), plan['stages'][0])
        query = '''import sqlite3,json
c=sqlite3.connect('/broker-state/leases.sqlite')
i='01a0f87f-bef9-739b-b889-8d5b49ee988f'
r=json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(i,)).fetchone()[0])
t=json.loads(c.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(i,)).fetchone()[0])
print(json.dumps({'red':r['red'],'review_status':t['status'],'review_manifest':t.get('manifest_sha256')}))
'''
        proof = json.loads(subprocess.check_output(['docker', 'exec', PROJECT + '-execution-broker-1',
                                                   'python3', '-c', query], text=True))
        if (proof['red']['exit_code'] != 1 or proof['red']['manifest_sha256'] != RED_MANIFEST
                or proof['red']['test_sha256'] != {'tests/test_feedback_filter_client.py': TEST_HASH}
                or proof['review_status'] != 'approved' or proof['review_manifest'] != RED_MANIFEST):
            raise ValueError('accepted frozen Red and independent review required')
        instruction = (marker + '\nONE VERIFIED CONTEXT RECOVERY. The prior implementation '
            'ended with Context length exceeded before producing code. Broker now starts a '
            'fresh conversation for every native task, while preserving your assigned workspace. '
            'PHASE 2 IMPLEMENTATION ONLY. Red already exists and independent test review approved '
            'manifest ' + RED_MANIFEST + '. Never replay Red, replace the new test, or edit ANY tests. '
            'Backend is already delivered at a80d4c4dc1e4f056c0e2e804329ff259d274f46a; '
            'do not reimplement API or use the old adfc base. Implement only the declared UI files '
            'app/static/app.js, app/static/index.html, app/static/style.css, following the C2 brief. '
            'Read the frozen test and current UI only as needed, in bounded sections. '
            'Use actual file tools with path/content (each file <=32768 bytes); no helper files '
            'or terminal writes. Run the pinned FULL suite: cd /workspace && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'Deliver Green with unchanged test hashes; controller handles immutable review/CI/QA. '
            'No promises or simulated calls count as implementation.')
        wakeup = cli('wakeup', 'create', ISSUE, '--agent-id', AUTHOR, '--event', 'task.completed',
                     '--task-id', SOURCE, '--mode', 'once', '--instruction', instruction)
    else:
        wakeup = wakeups[0]
    receipt = {'stage': 'registered', 'source_task': SOURCE, 'wakeup_id': wakeup['id'],
               'red_manifest': RED_MANIFEST, 'test_hash': TEST_HASH, 'at': time.time()}
    save_receipt(PRIVATE / 'filter-context-recovery.json', receipt)
    deadline = time.time() + 90
    while time.time() < deadline:
        new = [r for r in cli('runs', ISSUE) if r.get('wakeup_id') == wakeup['id'] and r.get('agent_id') == AUTHOR]
        if len(new) > 1:
            raise ValueError('duplicate context repair tasks')
        if new:
            route['enabled'] = True
            broker_post('/v1/delivery-routes', route)
            receipt.update(stage='supervisor_resumable', task_id=new[0]['id'])
            save_receipt(PRIVATE / 'filter-context-recovery.json', receipt)
            ledger['context_recovery'] = receipt
            ledger.update(stage='working', active='FILTERUI-1', updated_at=time.time())
            for key in ('category', 'owner', 'next_action'):
                ledger.pop(key, None)
            save_receipt(ledger_path, ledger)
            print(json.dumps(receipt))
            return
        time.sleep(2)
    raise TimeoutError('context correction dispatch deadline; registration preserved')


def main():
    with (PRIVATE / 'controller-locks' / 'FILTER-1-DELIVERY.lock').open('a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return resume()


if __name__ == '__main__':
    main()
