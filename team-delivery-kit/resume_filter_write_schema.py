"""One scoped retry after a verified malformed-write schema correction."""
import fcntl
import hashlib
import json
import os
import subprocess
import time

from dependent_sequence import load_plan, read_json, verify_predecessor
from evalctl import PRIVATE, PROJECT
from portable_delivery import managed_handoff
from release_eval import save_receipt
from start_eval import check_model_budget, cli

ISSUE = '01a0f87f-bef9-739b-b889-8d5b49ee988f'
SOURCE = '01a0f8a9-51bc-7ba7-9d72-1ba120a439bc'
AUTHOR = 'ce91fe5b-f6dd-4798-8f8c-6d3618ea83a1'


def missing_write_path(messages):
    return any(m.get('type') == 'tool_result' and m.get('tool') == 'write_file'
               and 'could not prepare diff (path required)' in str(m.get('output', ''))
               for m in messages)


def main():
    plan = load_plan(os.environ['DELIVERY_KIT_SEQUENCE_PLAN'])
    if PROJECT != 'delivery-kit-port2' or plan['name'] != 'FILTER-1-DELIVERY':
        raise ValueError('isolated sequence required')
    path = PRIVATE / 'dependent-sequences' / (plan['name'] + '.json')
    recovery_path = PRIVATE / 'filter-write-schema-recovery.json'
    lock = PRIVATE / 'controller-locks' / (plan['name'] + '.lock')
    with lock.open('a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = read_json(path)
        if not ledger or ledger.get('plan_sha256') != plan['sha256']:
            raise ValueError('sequence drift')
        receipt = read_json(recovery_path)
        if receipt and receipt.get('stage') == 'supervisor_resumable':
            if receipt.get('source_task') != SOURCE:
                raise ValueError('recovery identity drift')
            print(json.dumps({'stage': 'already_resumed'}))
            return
        if (ledger.get('stage') != 'blocked' or ledger.get('active') != 'FILTERUI-1'
                or ledger.get('completed') != ['FILTERAPI-1']
                or ledger.get('category') != 'RuntimeError:test_first_blocked:test_first_correction_failed_after_cto_diagnosis'):
            raise ValueError('exact failed correction required')
        proxy = json.loads(subprocess.check_output(
            ['docker', 'inspect', PROJECT + '-model-proxy-1'], text=True))[0]
        probe = read_json(PRIVATE / 'write-schema-probe.json')
        if (not proxy['State']['Running']
                or proxy['Config']['Image'] != 'delivery-kit-eval-model-proxy:20261001.10'
                or not probe or probe.get('status') != 'passed'
                or probe.get('proxy_image') != proxy['Image']):
            raise ValueError('strict write schema fix and real probe required')
        budget = check_model_budget()
        if budget['remaining'] < 64:
            raise ValueError('64 reserved calls required')
        verify_predecessor(read_json(PRIVATE / 'release-receipts' / 'FILTERAPI-1.json'), plan['stages'][0])
        marker = 'DELIVERY_HANDOFF ' + hashlib.sha256((ISSUE + ':' + SOURCE + ':write-schema-v1').encode()).hexdigest()
        wakeups = [w for w in cli('wakeup', 'list', ISSUE) if w.get('instruction', '').startswith(marker)]
        if len(wakeups) > 1:
            raise ValueError('duplicate schema-fix wakeups')
        if not wakeups:
            runs = cli('runs', ISSUE)
            authors = [r for r in runs if r.get('agent_id') == AUTHOR]
            source = max(authors, key=lambda r: (r.get('created_at') or '', r['id']))
            state = managed_handoff({'issue_id': ISSUE})['state']
            if (source['id'] != SOURCE or source['status'] != 'completed'
                    or any(r['status'] in ('running', 'queued') for r in runs)
                    or state['stage'] != 'test_first_blocked'):
                raise ValueError('exact idle malformed-write source required')
            query = ('import json; from native import task_messages; '
                     's=json.load(open("/broker-state/native.json")); '
                     'm=task_messages(s,"' + SOURCE + '"); '
                     'print(json.dumps([x for x in m if x.get("type")=="tool_result" and x.get("tool")=="write_file"]))')
            messages = json.loads(subprocess.check_output(['docker', 'exec', '-e', 'PYTHONPATH=/',
                PROJECT + '-execution-broker-1', 'python3', '-c', query], text=True))
            if not missing_write_path(messages):
                raise ValueError('malformed write evidence missing')
            instruction = (marker + '\nONE CONTROLLER VERIFIED TOOL-SCHEMA CORRECTION. '
                'Your prior write_file call lacked path and failed BEFORE edit approval. '
                'The proxy now sends strict required path/content arguments; a real probe passed. '
                'This is PHASE 1 TESTS ONLY, not a general permission grant. '
                'Use write_file with a JSON object containing path exactly '
                '"/workspace/tests/test_feedback_filter_client.py" and content containing the COMPLETE '
                'corrected test file, under 32768 UTF-8 bytes. No prose or code fences as arguments. '
                'Keep the already-working API guards if useful, but add actual browser-client '
                'behavioral tests for the C2 criteria, which are missing from the original file. '
                'Exercise the current real app.js; do not fabricate a passing harness or edit '
                'product code or pre-existing tests. Do not write helper files, /tmp probes, '
                'terminal heredocs or shell write workarounds. Run only the pinned full suite: '
                'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
                'The controller must capture genuine Red before implementation. '
                'A further failure stays visible and is not retried identically.')
            wakeup = cli('wakeup', 'create', ISSUE, '--agent-id', AUTHOR, '--event', 'task.completed',
                         '--task-id', SOURCE, '--mode', 'once', '--instruction', instruction)
        else:
            wakeup = wakeups[0]
        receipt = {'stage': 'registered', 'issue_id': ISSUE, 'source_task': SOURCE,
                   'wakeup_id': wakeup['id'], 'proxy_image': proxy['Image'], 'at': time.time()}
        save_receipt(recovery_path, receipt)
        deadline = time.time() + 90
        while time.time() < deadline:
            new = [r for r in cli('runs', ISSUE) if r.get('agent_id') == AUTHOR
                   and r.get('wakeup_id') == wakeup['id']]
            if len(new) > 1:
                raise ValueError('duplicate schema recovery execution')
            if new:
                receipt.update(stage='supervisor_resumable', recovery_task=new[0]['id'])
                save_receipt(recovery_path, receipt)
                ledger['write_schema_recovery'] = receipt
                ledger['previous_schema_failure'] = ledger['category']
                ledger.update(stage='working', updated_at=time.time())
                for key in ('category', 'owner', 'next_action'):
                    ledger.pop(key, None)
                save_receipt(path, ledger)
                print(json.dumps({'stage': 'supervisor_resumable', 'recovery_task': new[0]['id']}))
                return
            time.sleep(2)
        raise TimeoutError('schema recovery dispatch deadline; registration preserved')


if __name__ == '__main__':
    main()
