"""Durable controller-local Git binding, never an agent report endpoint.

Only the trusted local candidate bridge records its independently verified Git
proof. Structural checks here bind it to the immutable native capture; they
are not a substitute for that bridge's actual Git object verification.
"""
import json
try:
    from . import quality_delivery_capture as delivery,controller_maintenance as maintenance,validation_job
except ImportError:
    import quality_delivery_capture as delivery,controller_maintenance as maintenance,validation_job

quality=delivery.quality
require=delivery.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_candidate_bindings('
        'request_id TEXT PRIMARY KEY,identity TEXT,receipt TEXT,identity_sha256 TEXT,receipt_sha256 TEXT)')


def validate(identity,receipt):
    packet=identity['packet'];d=packet['descriptor'];plan=quality.validate(packet['plan'])
    candidate=receipt['candidate'];proof=candidate['git_proof']
    ref='refs/delivery-kit/quality/'+plan['run_id']+'/'+d['task_id']
    require(identity['namespace']==d['namespace'] and identity['request_id']==d['request_id']
        and d['plan_sha256']==quality.digest(plan) and d['issue_id']==plan['issue_id'] and d['run_id']==plan['run_id']
        and receipt['operation']=='controller_quality_git_binding_v2' and receipt['stage']=='awaiting_green'
        and receipt['request_id']==d['request_id'] and receipt['task_id']==d['task_id']
        and receipt['manifest_sha256']==d['manifest_sha256'] and receipt['commit_sha']==candidate['commit_sha']
        and candidate['operation']=='local_quality_candidate_v2' and candidate['stage']=='ready'
        and candidate['request_id']==d['request_id'] and candidate['source_task']==d['task_id'] and candidate['ref']==ref
        and proof['operation']=='verified_delivery_commit_v2' and proof['commit_sha']==candidate['commit_sha']
        and proof['base_sha']==plan['base_sha'] and proof['plan_sha256']==quality.digest(plan)
        and proof['manifest_sha256']==d['manifest_sha256'] and proof['frozen_tests']==packet['frozen_tests']
        and set(proof['git_files'])==set(d['file_inventory'])
        and isinstance(proof['changed_paths'],list) and bool(set(proof['changed_paths'])&set(plan['product_files']))
        and set(proof['changed_paths'])<=set(plan['product_files'])|set(plan['new_tests'])
        and all(value.get(k) is False for value in (receipt,candidate,proof)
            for k in ('execution_authorized','merge_authorized','delivery_approval'))
        and receipt['green_approved'] is False)
    for key in ('commit_sha','tree_sha'):quality.sha(proof[key],40)
    for item in proof['git_files'].values():
        require(set(item)=={'mode','blob'} and item['mode'] in ('100644','100755'));quality.sha(item['blob'],40)


def load(b,request):
    delivery.admission.enrollment.canonical(request)
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT identity,receipt,identity_sha256,receipt_sha256 FROM quality_candidate_bindings '
            'WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    identity,receipt=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(identity)==row[2] and quality.digest(receipt)==row[3]
        and identity['namespace']==b.PREFIX and identity['request_id']==request)
    validate(identity,receipt)
    context,state=delivery.load(b,request);d=identity['packet']['descriptor']
    require(quality.digest(context)==d['capture_context_sha256'] and quality.digest(state)==d['capture_state_sha256'])
    return identity,receipt


def record(b,request,packet,repository,candidate):
    """Controller process only: caller must have performed real Git verification."""
    require(delivery.candidate_packet(b,request)==packet)
    d=packet['descriptor']
    identity=dict(namespace=b.PREFIX,request_id=request,packet=packet,repository=repository)
    receipt=dict(operation='controller_quality_git_binding_v2',stage='awaiting_green',request_id=request,
        task_id=d['task_id'],manifest_sha256=d['manifest_sha256'],commit_sha=candidate['commit_sha'],candidate=candidate,
        execution_authorized=False,green_approved=False,merge_authorized=False,delivery_approval=False)
    validate(identity,receipt)
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves local candidate before registration')
        initialize(con)
        source=con.execute('SELECT context_sha256,state_sha256 FROM quality_delivery_captures WHERE request_id=?',
            (request,)).fetchone()
        require(source is not None and tuple(source)==(d['capture_context_sha256'],d['capture_state_sha256']))
        con.execute('INSERT OR IGNORE INTO quality_candidate_bindings VALUES(?,?,?,?,?)',
            (request,json.dumps(identity,sort_keys=True),json.dumps(receipt,sort_keys=True),quality.digest(identity),quality.digest(receipt)))
        row=con.execute('SELECT identity_sha256,receipt_sha256 FROM quality_candidate_bindings WHERE request_id=?',(request,)).fetchone()
        require(tuple(row)==(quality.digest(identity),quality.digest(receipt)))
    return receipt
