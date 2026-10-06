"""One bounded registration of the existing, narrowly qualified restart diagnosis.

No author retry, status reset or generic commands. The broker independently
checks interruption identity, no admitted tools/Red, idle leases and preservation.
"""
import json
from pathlib import Path
import re
import subprocess
import uuid

from release_eval import save_receipt

CATEGORY = 'test_first_blocked:test_first_correction_failed_after_cto_diagnosis'

REGISTER = '''import json,sys,broker as b,native,host_restart_recovery as recovery
issue,source=sys.argv[1:]
with b.db() as c:
 route=json.loads(c.execute("SELECT config FROM delivery_routes WHERE issue_id=?",(issue,)).fetchone()[0])
settings=json.loads((b.STATE/'native.json').read_text())
runs=native.issue_task_runs(settings,issue)
authors=sorted([r for r in runs if r.get('agent_id')==route['author']],key=lambda r:(r.get('created_at') or '',r['id']))
if len(authors)<2 or authors[-1]['id']!=source: raise ValueError('restart source drift')
print(json.dumps(recovery.register(b,dict(issue_id=issue,source_task=source,interrupted_task=authors[-2]['id']))))
'''
LOOKUP = '''import json,sys,broker as b
with b.db() as c:
 exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='host_restart_recoveries'").fetchone()
 row=c.execute("SELECT receipt FROM host_restart_recoveries WHERE issue_id=?",(sys.argv[1],)).fetchone() if exists else None
 print(row[0] if row else 'null')
'''


def eligible(status, managed):
    if status.get('stage') != 'escalation_required' or status.get('category') != CATEGORY:
        return False
    if not managed or not managed.get('route', {}).get('enabled'):
        return False
    route, state = managed['route'], managed.get('state') or {}
    data = json.loads(state.get('data', '{}'))
    return (route.get('issue_id') == status.get('issue_id') and route.get('test_first') is True
        and state.get('stage') == 'test_first_blocked' and data.get('phase') == 'test_first'
        and data.get('error') == 'test_first_correction_failed_after_cto_diagnosis'
        and route.get('author') != route.get('cto') and bool(state.get('source_task')))


def invoke(instance, script, *identity):
    result = subprocess.run(['docker', 'exec', '-e', 'PYTHONPATH=/',
        instance + '-execution-broker-1', 'python', '-c', script, *identity],
        capture_output=True, text=True, timeout=60)
    if result.returncode:
        # Never copy stderr, runtime configuration or credentials into receipts.
        raise ValueError('restart_registration_rejected')
    return json.loads(result.stdout)


def valid(receipt, issue, source):
    return (isinstance(receipt, dict) and isinstance(receipt.get('request'), dict)
        and isinstance(receipt.get('proof'), dict)
        and receipt.get('request', {}).get('issue_id') == issue
        and receipt['request'].get('source_task') == source
        and receipt.get('proof', {}).get('baseline_unchanged') is True
        and receipt['proof'].get('red_verified') is False
        and receipt['proof'].get('delivery_approval') is False
        and receipt.get('author_retry_authorized') is False
        and receipt.get('delivery_approval') is False)


def reconcile(private, instance, status, managed, operation=invoke):
    if not eligible(status, managed):
        return False
    issue, source = status['issue_id'], managed['state']['source_task']
    if not re.fullmatch(r'[A-Z][A-Z0-9]{1,31}-[1-9][0-9]{0,5}', status['label']):
        raise ValueError('restart diagnosis label invalid')
    for value in (issue, source):
        if str(uuid.UUID(value)) != value:
            raise ValueError('restart diagnosis identity invalid')
    path = Path(private) / 'host-service' / (status['label'] + '.restart-diagnosis.json')
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('unsafe restart diagnosis receipt')
    identity = dict(issue_id=issue, source_task=source)
    if path.exists():
        prior = json.loads(path.read_text())
        if prior.get('identity') != identity:
            return False  # Another failure requires a new explicit diagnosis.
        if prior.get('stage') == 'registered':
            return valid(prior.get('receipt'), issue, source)
        if prior.get('stage') != 'intent':
            return False
        # A crash after sending registration must never send it again. Only
        # discover the broker's durable result; absence remains visibly blocked.
        script, args = LOOKUP, (issue,)
    else:
        save_receipt(path, dict(identity=identity, stage='intent',
            next_action='reconcile_broker_receipt_without_redispatch'))
        script, args = REGISTER, (issue, source)
    try:
        receipt = operation(instance, script, *args)
        accepted = valid(receipt, issue, source)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        # Retain intent for read-only reconciliation after uncertain transport.
        save_receipt(path, dict(identity=identity, stage='intent',
            reason='registration_transport_or_qualification_unconfirmed',
            next_action='read_broker_receipt_then_technical_diagnosis_if_absent'))
        return False
    if accepted:
        save_receipt(path, dict(identity=identity, stage='registered', receipt=receipt))
        return True
    save_receipt(path, dict(identity=identity, stage='diagnosis_blocked',
        reason='no_qualified_registration', author_retry_authorized=False,
        next_action='cto_inspect_preserved_failure_without_author_retry'))
    return False
