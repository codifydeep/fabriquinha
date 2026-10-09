"""One evidence-bound technical replan after installed observation qualification.

The fixed synthetic probe does not diagnose historical edits. A fresh CTO decision
is still required; original plan approvals, depth, attempts and delivery gates stay.
"""
import hashlib
import json
from pathlib import Path
import time
try:
    import handoffs, test_first_job, remediation_admission, generic_remediation_driver
except ImportError:
    from broker import handoffs, test_first_job, remediation_admission, generic_remediation_driver


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def validate_probe(value,source_sha,handler_sha):
    cases=value.get('cases',[])
    if (value.get('operation')!='installed_patch_persistence_probe_v1'
            or value.get('worker_observation_qualified') is not True or value.get('worker_uid')!=10000
            or value.get('probe_sha256')!=source_sha or value.get('handler_sha256')!=handler_sha
            or value.get('synthetic_only') is not True or value.get('historical_cause')!='unknown'
            or any(value.get(k) is not False for k in ('product_files_modified','author_retry_authorized','delivery_approval'))
            or len(cases)!=3 or [c.get('kind') for c in cases]!=
                ['observed_persistent_change','observed_unchanged_success','observed_later_change']):
        raise ValueError('actual installed fixed observation probe required')
    for c in cases:
        h=c.get('handler',{}).get('test_hash_observation',{})
        if (h.get('before_sha256')!=c.get('before') or h.get('after_sha256')!=c.get('after')
                or h.get('changed')!=(c['before']!=c['after'])
                or h.get('delivery_approval') is not False or h.get('author_retry_authorized') is not False):
            raise ValueError('independent before/after hashes required')


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS patch_observation_replans(source_task TEXT PRIMARY KEY,proof TEXT)')


def qualified(c,issue,source,data,image):
    initialize(c)
    row=c.execute('SELECT proof FROM patch_observation_replans WHERE source_task=?',(source,)).fetchone()
    proof=data.get('patch_observation_replan')
    if not row or not isinstance(proof,dict) or json.loads(row[0])!=proof:return False
    plan=c.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(proof['plan_source'],)).fetchone()
    if not plan:return False
    config,state=map(json.loads,plan)
    bound=generic_remediation_driver.binding(config,state)
    return (proof['issue_id']==issue and proof['source_task']==source and proof['image']==image
            and proof['plan_binding']==bound and proof['author_retry_authorized'] is False
            and proof['delivery_approval'] is False and proof['attempt_limit']==1)


def register(b,route,source,incident,state,fx):
    recovery=state.get('transport_recovery',{}).get('state',{})
    if recovery.get('stage')!='diagnosed_hold':return False
    program=Path('/probe_patch_persistence.py')
    if not program.is_file() or program.is_symlink():return False
    with b.db() as c:
        initialize(c)
        if c.execute('SELECT 1 FROM patch_observation_replans WHERE source_task=?',(source,)).fetchone():return False
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return True
        executions=[(r[0],*map(json.loads,r[1:])) for r in c.execute('SELECT source_task,contract,state FROM remediation_executions')]
        parents=[r for r in executions if r[2].get('r1_runtime',{}).get('issue_id')==route['issue_id']]
        if len(parents)!=1:raise ValueError('one original R1 plan lineage required')
        parent,contract,execution=parents[0]
        current=handoffs.load(c,source)
        if not current or current['stage']!='test_first_blocked':return False
        previous=json.loads(current['data'])
        if c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(route['issue_id'],)).fetchone():return False
    config,plan=remediation_admission.Effects(b).plan(parent)
    bound=generic_remediation_driver.binding(config,plan)
    if (contract.get('original_depth')!=2 or execution.get('r1_gate')
            or contract.get('plan_sha256')!=bound['plan_sha256']
            or execution['r1_runtime']['writable_paths']!=['/workspace/'+p for p in route['test_first_files']]
            or contract.get('baseline_edits_allowed') is not False
            or contract.get('historical_snapshots_editable') is not False):
        raise ValueError('unchanged tests-only original approved plan required')
    task=fx.runs()
    if any(t.get('status') in ('queued','dispatched','running') for t in task):return True
    matches=[t for t in task if t['id']==recovery['task_id']]
    if (len(matches)!=1 or matches[0].get('status')!='completed' or matches[0].get('agent_id')!=route['cto']
            or fx.decision(matches[0])!=recovery['recommendation']):raise ValueError('actual preserved CTO recommendation required')
    with b.db() as c:
        test_first_job.initialize(c)
        old_job=c.execute('SELECT identity FROM test_first_jobs WHERE job_key=?',(recovery['task_id']+':copy',)).fetchone()
    job_image=json.loads(old_job[0])['payload']['Image'] if old_job else b.IMAGE
    payload=dict(Image=job_image,User='0:0',Entrypoint=['python'],Cmd=['/probe_patch_persistence.py'],WorkingDir='/tmp',
        Env=['PYTHONDONTWRITEBYTECODE=1','HERMES_HOME=/tmp/hermes','HERMES_WRITE_SAFE_ROOT=/workspace',
             'TERMINAL_ENV=local','TERMINAL_CWD=/workspace','DELIVERY_EXECUTION_MODE=implementation',
             'HERMES_FENCED_INPLACE_WRITES=1','DELIVERY_PROBE_REQUIRE_OBSERVATION=1'],
        Labels={'delivery-kit.purpose':'patch-observation-qualification'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],CapAdd=['SETUID','SETGID'],
            Tmpfs={'/tmp':'rw,size=128m,mode=1777','/workspace':'rw,size=1m,mode=1777'}))
    with b.db() as c:
        try:result=test_first_job.run(b,c,recovery['task_id'],'copy',payload)
        except TimeoutError:return True  # Observe the same durable job, not a new POST.
    if result['exit_code']!=0:raise ValueError('fixed observation job failed; no author retry')
    value=json.loads(result['output'])
    validate_probe(value,hashlib.sha256(program.read_bytes()).hexdigest(),
                   hashlib.sha256(Path('/opt/hermes/tools/file_tools.py').read_bytes()).hexdigest())
    proof=dict(operation='qualified_patch_observation_replan_v1',source_task=source,issue_id=route['issue_id'],
        image=b.IMAGE,job_image=job_image,plan_source=parent,plan_binding=bound,incident_identity_sha256=digest(incident),
        recommendation_task=recovery['task_id'],probe=value,job_output_sha256=result['output_sha256'],
        previous_handoff=previous,attempt_limit=1,author_retry_authorized=False,delivery_approval=False)
    data={**previous,'patch_observation_replan':proof,
        'required_action':'CTO decide one observed tests-only correction under original approved plan'}
    for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):data.pop(field,None)
    # Resolved inspection errors remain in previous_handoff, not the active view.
    for field in ('control_error','control_error_count'):data.pop(field,None)
    with b.db() as c:
        current=handoffs.load(c,source)
        if not current or current['data']!=json.dumps(previous,sort_keys=True):
            if not current or json.loads(current['data'])!=previous:raise ValueError('replan handoff drift')
        c.execute('INSERT INTO patch_observation_replans VALUES(?,?)',(source,json.dumps(proof,sort_keys=True)))
        handoffs.save(c,source,route['issue_id'],'technical_decision_required',route['cto'],data,time.time())
    return True
