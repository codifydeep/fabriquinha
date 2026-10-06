"""One evidence-bound controller diagnosis for a changed read capacity policy."""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
try:import handoffs,native
except ImportError:from broker import handoffs,native

PROXY_IMAGE='sha256:7b05d29e6a58ae7600ecf552bcf42e4a75f175ed67f6183a2fd94550b4118018'


def validate(probe):
    if (not isinstance(probe,dict) or probe.get('operation')!='frozen_native_read_page_probe_v2'
            or any(probe.get(k) is not True for k in ('baseline_unchanged','all_lines_observed','snapshot_unchanged'))
            or any(probe.get(k) is not False for k in ('delivery_approval','agent_inspection_verified','full_rpc_qualified'))
            or type(probe.get('model_calls')) is not int or probe['model_calls']!=0
            or probe.get('historical_tool_turns')!=40
            or any(type(probe.get(k)) is not int for k in ('calls_50','calls_200','files'))
            or not 20<=probe['calls_50']<=64 or not 1<=probe['calls_200']<=probe['calls_50']//2
            or not 1<=probe['files']<=5
            or any(not re.fullmatch(r'[a-f0-9]{64}',str(probe.get(k,'')))
                   for k in ('manifest_sha256','policy_sha256'))
            or not isinstance(probe.get('test_sha256'),dict) or len(probe['test_sha256'])!=1
            or any(not re.fullmatch(r'tests/test_[A-Za-z0-9_]+\.py',p)
                   or not re.fullmatch(r'[a-f0-9]{64}',str(h)) for p,h in probe['test_sha256'].items())):
        raise ValueError('qualified nonapproving read capacity experiment required')
    for key in ('source_task','session_id'):
        if str(uuid.UUID(probe[key]))!=probe[key]:raise ValueError('canonical experiment identity required')


def register(b,issue,task,probe):
    validate(probe)
    if str(uuid.UUID(issue))!=issue or probe['source_task']!=task:
        raise ValueError('exact experiment source required')
    with b.LOCK,b.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS read_capacity_diagnoses(issue_id TEXT PRIMARY KEY,receipt TEXT)')
        old=c.execute('SELECT receipt FROM read_capacity_diagnoses WHERE issue_id=?',(issue,)).fetchone()
        if old:
            receipt=json.loads(old[0])
            if receipt['source_task']!=task or receipt['probe']!=probe:raise ValueError('capacity diagnosis already consumed')
            return receipt
        row=handoffs.load(c,task)
        route_row=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        route=json.loads(route_row[0]) if route_row else {}
        latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        if (not row or row['issue_id']!=issue or row['stage']!='test_first_blocked'
                or json.loads(row['data']).get('error')!='test_first_correction_failed_after_cto_diagnosis'
                or route.get('enabled') is not True or route.get('test_first') is not True
                or route['cto']==route['author'] or latest[0]!=task
                or route['test_first_files']!=list(probe['test_sha256'])
                or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
            raise ValueError('idle latest blocked pre-Red author required')
        snapshot=c.execute('SELECT status,volume FROM failed_execution_snapshots WHERE task_id=?',(task,)).fetchone()
        binding=c.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(task,)).fetchone()
        session=c.execute("SELECT session_id FROM acp_events WHERE request_id=? AND method='session/new' AND success=1",
                          (binding[0],)).fetchall() if binding else []
        if (not snapshot or snapshot['status']!='complete' or len(session)!=1
                or session[0][0]!=probe['session_id']):raise ValueError('frozen snapshot and exact native session required')
        settings=json.loads((b.STATE/'native.json').read_text());runs=native.issue_task_runs(settings,issue)
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        failed=max(authors,key=lambda r:(r.get('created_at') or '',r['id'])) if authors else {}
        if (failed.get('id')!=task or failed.get('status')!='failed'
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest failed author and idle native issue required')
        parents=[json.loads(r[0]) for r in c.execute("SELECT data FROM delivery_handoffs WHERE issue_id=? AND stage='test_first_cto_correction_wait'",(issue,))]
        parents=[p for p in parents if p.get('test_first_correction_wakeup')==failed.get('wakeup_id')
                 and p.get('decision',{}).get('action')=='request_correction']
        if len(parents)!=1 or not any(r['id']==parents[0].get('cto_task') and r.get('agent_id')==route['cto']
                and r.get('status')=='completed' for r in runs):
            raise ValueError('exact independent CTO corrective lineage required')
        from author_read_policy import page_size
        if hashlib.sha256(Path(page_size.__code__.co_filename).read_bytes()).hexdigest()!=probe['policy_sha256']:
            raise ValueError('measured policy not installed')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if proxy['Image']!=PROXY_IMAGE or not proxy['State']['Running']:raise ValueError('measured proxy not installed')
        diagnostic=dict(kind='verified_read_capacity_change',issue_id=issue,task_id=task,
            manifest_sha256=probe['manifest_sha256'],test_sha256=probe['test_sha256'],
            tests_executed=False,red_verified=False,delivery_approval=False,
            reason='The preserved session used 40 tool turns, including 31 distinct reads; no Red exists. '
                'A read-only experiment on the exact frozen snapshot preserved every baseline byte and '
                'read all four required files in 9 calls instead of 28. New registered revisions now '
                'use bounded 200-line pages, with actual full-line coverage still mandatory. '
                'The original RPC cause remains unqualified; this is a measured capacity change, not '
                'a delivery or automatic author retry. Inspect the preserved new test and prescribe '
                'one concrete tests-only action with the unchanged full pinned suite, or escalate.')
        receipt=dict(operation='read_capacity_diagnosis_v1',issue_id=issue,source_task=task,
            probe=probe,snapshot_volume=snapshot['volume'],prior=dict(row),diagnostic=diagnostic,
            provenance='operator_verified_frozen_native_read_experiment',
            author_retry_authorized=False,delivery_approval=False,at=time.time())
        data=json.loads(row['data']);data.update(phase='test_first',source_task=task,
            read_capacity_diagnosis=receipt,diagnostic=diagnostic,error='read_capacity_diagnosis_required')
        c.execute('INSERT INTO read_capacity_diagnoses VALUES (?,?)',(issue,json.dumps(receipt,sort_keys=True)))
        handoffs.save(c,task,issue,'technical_decision_required',route['cto'],data,time.time())
        return receipt


def qualified(c,issue,task,data):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='read_capacity_diagnoses'").fetchone():return False
    row=c.execute('SELECT receipt FROM read_capacity_diagnoses WHERE issue_id=?',(issue,)).fetchone()
    receipt=json.loads(row[0]) if row else {}
    if not (receipt and receipt==data.get('read_capacity_diagnosis') and receipt.get('source_task')==task
            and receipt.get('issue_id')==issue and receipt.get('operation')=='read_capacity_diagnosis_v1'
            and receipt.get('diagnostic')==data.get('diagnostic')
            and receipt.get('probe',{}).get('source_task')==task
            and receipt.get('author_retry_authorized') is False and receipt.get('delivery_approval') is False):return False
    try:validate(receipt['probe'])
    except (ValueError,KeyError,TypeError):return False
    return True
