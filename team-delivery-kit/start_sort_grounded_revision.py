"""Resume the bounded child controller only after its fresh CTO certificate."""
import hashlib
import json
import os
from evalctl import PRIVATE, PROJECT
from portable_contract import from_environment
from portable_delivery import managed_handoff
from portable_run_spec import validate
from portable_test_revision_recovery import schedule, next_revision_depth
from start_eval import read_model_budget


def main():
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('isolated port2 only')
    label = 'TESTREV544C9E915718-1'
    context = json.loads((PRIVATE / ('portable-context-' + label + '.json')).read_text())
    if context['issue_id'] != '01a0fa1e-05ca-7bf1-b4e9-423d586d440c':
        raise ValueError('scope drift')
    contract = from_environment()
    spec = validate(json.loads((PRIVATE / 'test-revision-recovery' /
                               (label + '.run.json')).read_text()), contract)
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if context['run_spec_sha256'] != digest:
        raise ValueError('immutable intake drift')
    managed = managed_handoff(context)
    if not managed or managed['route']['enabled'] or managed['state']['stage'] != 'test_revision_required':
        raise ValueError('paused, valid CTO proposal required')
    data = json.loads(managed['state']['data'])
    revision = '991ade4c3010493e3c88a39bfa46f901302cbb961aca381e5ae1cde0b4ab4fe9:controller-capture-v3'
    if data.get('diagnostic_revision') not in (revision, revision + ':capture-format-v1'):
        raise ValueError('grounded diagnosis identity drift')
    next_revision_depth(context, managed, '1')
    if read_model_budget()['remaining'] < 64:
        raise ValueError('bounded revision budget unavailable')
    os.environ['DELIVERY_KIT_TEST_REVISION_DEPTH'] = '1'
    return schedule(PRIVATE, context, spec, contract, managed)


if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True))
