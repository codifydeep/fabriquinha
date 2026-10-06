"""Operator-qualified changed-condition diagnosis, never an author retry."""
import hashlib
import json
import re
import time
try:import handoffs,native
except ImportError:from broker import handoffs,native

PROXY_IMAGE='sha256:ae1f1d76281235060a5001b07d63c701d79ba420055df3f6b809b7072f8c5734'


def validate(probe):
    if (probe.get('operation')!='postwrite_snapshot_integrity_v1'
            or probe.get('verified') is not True or probe.get('baseline_unchanged') is not True
            or probe.get('changed') is not True or probe.get('red_verified') is not False
            or probe.get('delivery_approval') is not False
            or any(not re.fullmatch(r'[a-f0-9]{64}',str(probe.get(k,''))) for k in
                   ('manifest_sha256','new_test_sha256','previous_test_sha256'))
            or not isinstance(probe.get('previous_methods'),list)
            or not isinstance(probe.get('current_methods'),list)):
        raise ValueError('verified changed snapshot required for diagnosis')


def register(b,issue,task,probe,*,after_patch=False):
    validate(probe)
    table='postpatch_diagnoses' if after_patch else 'postwrite_diagnoses'
    with b.LOCK,b.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS '+table+'(issue_id TEXT PRIMARY KEY,receipt TEXT)')
        old=c.execute('SELECT receipt FROM '+table+' WHERE issue_id=?',(issue,)).fetchone()
        if old:
            receipt=json.loads(old[0])
            if receipt['source_task']!=task or receipt['probe']!=probe:raise ValueError('diagnosis already consumed')
            return receipt
        row=handoffs.load(c,task);route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        if (not row or row['issue_id']!=issue or row['stage']!='test_first_blocked'
                or json.loads(row['data']).get('error')!='test_first_correction_failed_after_cto_diagnosis'
                or route.get('enabled') is not True or route['cto']==route['author']
                or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
            raise ValueError('idle blocked pre-Red incident required')
        snapshot=c.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(task,)).fetchone()
        if not snapshot or snapshot['status']!='complete':raise ValueError('frozen failed snapshot required')
        runs=native.issue_task_runs(json.loads((b.STATE/'native.json').read_text()),issue)
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        failed=max(authors,key=lambda r:(r.get('created_at') or '',r['id']))
        if failed['id']!=task or failed['status']!='failed':raise ValueError('latest failed author required')
        if after_patch:
            predecessor=c.execute('SELECT receipt FROM postwrite_diagnoses WHERE issue_id=?',(issue,)).fetchone()
            predecessor=json.loads(predecessor[0]) if predecessor else {}
            parent=handoffs.load(c,predecessor.get('source_task',''));parent_data=json.loads(parent['data']) if parent else {}
            if (probe.get('methods_preserved') is not True or not parent
                    or parent['stage']!='test_first_cto_correction_wait'
                    or failed.get('wakeup_id')!=parent_data.get('test_first_correction_wakeup')
                    or parent_data.get('decision',{}).get('action')!='request_correction'):
                raise ValueError('preserved methods and exact CTO corrective lineage required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if proxy['Image']!=PROXY_IMAGE or not proxy['State']['Running']:raise ValueError('fixed proxy required')
        receipt=dict(operation='postwrite_phase_diagnosis_v1',issue_id=issue,source_task=task,
            probe=probe,snapshot_volume=snapshot['volume'],prior=dict(row),proxy_image=PROXY_IMAGE,
            provenance='operator_verified_snapshot_and_historical_proxy_metadata',
            author_retry_authorized=False,delivery_approval=False,at=time.time())
        if after_patch:receipt['repair_kind']='postpatch_transport_v2'
        diagnostic=dict(kind='postwrite_phase_failure',issue_id=issue,task_id=task,
            reason='A verified new-test write changed the source; the old read accumulator stalled. '
                   'The fixed proxy now fences inspection at the successful write. '
                   'The candidate replaced historical new-test method names; require targeted restoration '
                   'or independent justification, preserving all behavior. Missing symbols: '
                   + ', '.join(sorted(set(probe['previous_methods'])-set(probe['current_methods'])))
                   + '. No Red or approval exists.',
            manifest_sha256=probe['manifest_sha256'],test_sha256={route['test_first_files'][0]:probe['new_test_sha256']},
            tests_executed=False,red_verified=False,delivery_approval=False)
        if after_patch:
            diagnostic['reason']=('The author restored historical test symbols through a completed patch. '
                'All baseline bytes and historical symbols are preserved in the changed snapshot. '
                'The read dispatcher reused one key across streaming and JSON, and post-patch inspection '
                'mixed source versions. Both contracts are now fixed and offline history replay passed. '
                'Inspect the preserved test and run the unchanged full pinned suite before changing any '
                'bytes. A failed native turn is not Red or approval; no product edits or test weakening.')
        data=json.loads(row['data']);data.update(phase='test_first',source_task=task,
            diagnostic=diagnostic,postwrite_diagnosis=receipt,error='postwrite_phase_failure')
        c.execute('INSERT INTO '+table+' VALUES (?,?)',(issue,json.dumps(receipt,sort_keys=True)))
        handoffs.save(c,task,issue,'technical_decision_required',route['cto'],data,time.time())
        return receipt


def qualified(c,issue,task,data):
    table='postpatch_diagnoses' if data.get('postwrite_diagnosis',{}).get('repair_kind')=='postpatch_transport_v2' else 'postwrite_diagnoses'
    if not c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():return False
    row=c.execute('SELECT receipt FROM '+table+' WHERE issue_id=?',(issue,)).fetchone()
    receipt=json.loads(row[0]) if row else {}
    return (receipt and receipt==data.get('postwrite_diagnosis') and receipt.get('source_task')==task
        and receipt.get('author_retry_authorized') is False and receipt.get('delivery_approval') is False)
