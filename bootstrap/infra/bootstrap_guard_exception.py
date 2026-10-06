"""Operator-only, CEO-authorized 2026-09-20; restore protection in finally."""
import json
from product_autonomy import Coordinator, api, atomic
from finalize_process_governance import finalize

def main():
    c=Coordinator()
    if not (c.board/'DRAIN').exists():
        raise PermissionError('dispatch must be drained')
    if c.native.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():
        raise PermissionError('active worker')
    pr=api('pulls/28')
    if pr['head']['sha']!='009a552c1620511f599185a4aa2e58b4f01b7b34' or pr['merged'] or pr['base']['ref']!='release/v0.1':
        raise PermissionError('authorized PR identity drift')
    path='branches/release%2Fv0.1/protection/required_status_checks'
    original=api(path)
    restore=dict(strict=original['strict'],checks=original['checks'])
    if [v['context'] for v in restore['checks']]!=['governance','hermes-independent-review']:
        raise PermissionError('unexpected protection configuration')
    backup=c.root/'governance-bootstrap-protection-20260920.json'
    if backup.exists() and json.loads(backup.read_text())!=restore:
        raise PermissionError('protection backup drift')
    atomic(backup,restore)
    try:
        api(path,'PATCH',dict(strict=restore['strict'],checks=[v for v in restore['checks'] if v['context']!='governance']))
        result=finalize(c,'t_f4a400e6')
    finally:
        api(path,'PATCH',restore)
        actual=api(path)
        normalized=lambda checks: sorted((v['context'],str(v['app_id'])) for v in checks)
        if actual['strict']!=restore['strict'] or normalized(actual['checks'])!=normalized(restore['checks']):
            raise RuntimeError('CRITICAL: protection restoration verification failed; keep DRAIN')
    print(json.dumps(dict(pr=result['pr'],merge=result['merge'],signed_test_maintenance=True,protection_restored=True)))

if __name__=='__main__':main()
