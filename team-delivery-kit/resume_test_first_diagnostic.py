"""Evidence-bound recovery of the FILTER-1 missing-diagnostic incident only."""
import fcntl
import json
import os
import time

from dependent_sequence import load_plan, read_json, verify_predecessor
from evalctl import PRIVATE, PROJECT
from portable_delivery import managed_handoff
from prepare_issue_base import broker_post
from release_eval import save_receipt
from start_eval import check_model_budget, cli

ISSUE = '01a0f87f-bef9-739b-b889-8d5b49ee988f'
SOURCE = '01a0f89b-3746-75fb-9c7c-ec7e3ea0d94d'
CTO = '01a0f89d-6adf-72e8-82f3-d6a12e488c22'


def main():
    plan = load_plan(os.environ['DELIVERY_KIT_SEQUENCE_PLAN'])
    if PROJECT != 'delivery-kit-port2' or plan['name'] != 'FILTER-1-DELIVERY':
        raise ValueError('isolated incident identity required')
    path = PRIVATE / 'dependent-sequences' / (plan['name'] + '.json')
    lock = PRIVATE / 'controller-locks' / (plan['name'] + '.lock')
    with lock.open('a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = read_json(path)
        if not ledger or ledger.get('plan_sha256') != plan['sha256']:
            raise ValueError('sequence identity drift')
        recovery = ledger.get('diagnostic_recovery')
        if recovery:
            if recovery.get('source_task') != SOURCE or recovery.get('cto_task') != CTO:
                raise ValueError('recovery identity drift')
            print(json.dumps({'stage': 'already_resumed', 'sequence': plan['name']}))
            return
        if (ledger.get('stage') != 'blocked' or ledger.get('active') != 'FILTERUI-1'
                or ledger.get('completed') != ['FILTERAPI-1']
                or ledger.get('issues', {}).get('FILTERUI-1') != ISSUE
                or ledger.get('category') != 'RuntimeError:technical_decision_required:ValueError:Red must be an executed failing test suite'):
            raise ValueError('exact failed transition required')
        if check_model_budget()['remaining'] < 64:
            raise ValueError('diagnosis recovery requires 64 reserved calls')
        verify_predecessor(read_json(PRIVATE / 'release-receipts' / 'FILTERAPI-1.json'),
                           plan['stages'][0])
        broker_post('/v1/test-first-diagnostic-recovery',
                    {'issue_id': ISSUE, 'source_task': SOURCE, 'cto_task': CTO})
        state = managed_handoff({'issue_id': ISSUE})['state']
        data = json.loads(state['data'])
        if (data.get('diagnostic_retry') != 1
                or data.get('previous_cto_diagnosis', {}).get('cto_task') != CTO):
            raise ValueError('broker recovery receipt missing')
        ledger['diagnostic_recovery'] = {'source_task': SOURCE, 'cto_task': CTO,
            'previous_category': ledger['category'], 'manifest_sha256': data['diagnostic']['manifest_sha256'],
            'at': time.time()}
        ledger.update(stage='working', updated_at=time.time())
        for key in ('category', 'owner', 'next_action'):
            ledger.pop(key, None)
        save_receipt(path, ledger)
        cli('metadata', 'set', ISSUE, '--key', 'sequence_status', '--value',
            'recovering_cto_diagnosis', '--type', 'string')
        print(json.dumps({'stage': 'resumed_diagnosis', 'sequence': plan['name']}))


if __name__ == '__main__':
    main()
