"""Fixed v2 snapshot producer; persist intent before any Docker effect.

No agent commands, implicit volume adoption, source mutation or Red approval.
Uses the same per-source lock as capture and the existing durable copy-job
journal. Unknown create/start outcomes are observed, never blindly repeated.
"""
import json
try:
    from . import quality_red_capture as capture
    from . import controller_maintenance as maintenance,test_first_job,validation_job
except ImportError:
    import quality_red_capture as capture
    import controller_maintenance as maintenance,test_first_job,validation_job

require=capture.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_snapshot_intents('
        'task_id TEXT PRIMARY KEY,identity TEXT,state TEXT,identity_sha256 TEXT,state_sha256 TEXT)')


def save(b,task,identity,before,after):
    with b.LOCK,b.db() as con:
        changed=con.execute('UPDATE quality_snapshot_intents SET state=?,state_sha256=? '
            'WHERE task_id=? AND identity_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),capture.quality.digest(after),task,
                capture.quality.digest(identity),capture.quality.digest(before)))
        require(changed.rowcount==1)
    return after


def volume_identity(info,identity):
    require(isinstance(info,dict) and info.get('Name')==identity['name'] and info.get('Driver')=='local'
        and info.get('Scope')=='local' and info.get('Options') in (None,{})
        and isinstance(info.get('CreatedAt'),str) and 1<=len(info['CreatedAt'])<=100
        and info.get('Labels')==identity['labels'])
    return {k:info[k] for k in ('Name','Driver','Scope','CreatedAt','Labels')}


def prepare(b,task):
    capture.enrollment.canonical(task)
    with capture.observation_lock(b,task):
        try:return _prepare(b,task)
        except (ValueError,KeyError,TypeError) as failure:
            with b.db() as con:
                initialize(con)
                row=con.execute('SELECT identity,state,identity_sha256,state_sha256 FROM quality_snapshot_intents '
                    'WHERE task_id=?',(task,)).fetchone()
            if row:
                identity,state=json.loads(row[0]),json.loads(row[1])
                if (capture.quality.digest(identity)==row[2] and capture.quality.digest(state)==row[3]
                        and state.get('stage') not in ('technical_blocked','snapshot_copied')):
                    blocked=dict(stage='technical_blocked',owner=identity['techlead'],
                        snapshot_volume=identity['name'],copy_job=task+':copy',
                        incident=dict(category='snapshot_copy_rejected',source_task=task,automatic_retry=False,
                            next_action='Tech Lead inspect recorded volume/copy evidence; preserve the original task'),
                        execution_authorized=False,delivery_approval=False)
                    save(b,task,identity,state,blocked)
            raise ValueError('snapshot producer rejected; inspect preserved source and Docker intent') from failure


def _prepare(b,task):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT identity,state,identity_sha256,state_sha256 FROM quality_snapshot_intents '
            'WHERE task_id=?',(task,)).fetchone()
        if row:
            previous,state=json.loads(row[0]),json.loads(row[1])
            require(capture.quality.digest(previous)==row[2] and capture.quality.digest(state)==row[3]
                and state.get('stage') in ('prepared','volume_create_intent','copy_pending','snapshot_copied','technical_blocked')
                and state.get('execution_authorized') is False and state.get('delivery_approval') is False
                and capture.quality.digest(capture.enrollment.lookup(con,previous['source']['issue_id']))==previous['enrollment_sha256'])
            if state['stage'] in ('snapshot_copied','technical_blocked'):return state
        if maintenance.current(con):raise validation_job.Pending('maintenance pauses snapshot effects; observe original intent')
    e,plan,spec,binding,lead=capture.authorize_source(b,task)
    name=b.PREFIX+'-quality-red-'+task
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.test-first-task':task,'delivery-kit.quality-run':e['run_id'],
        'delivery-kit.lifecycle':'snapshot','com.docker.compose.project':b.PREFIX+'-tests',
        'com.docker.compose.volume':'quality-red-snapshot'}
    identity=dict(name=name,labels=labels,enrollment_sha256=capture.quality.digest(e),source=binding,
        techlead=lead,payload=capture.copy_payload(b,e,task,binding))
    if row:require(previous==identity)
    else:
        state=dict(stage='prepared',owner=e['author'],snapshot_volume=name,copy_job=task+':copy',
            execution_authorized=False,delivery_approval=False)
        with b.LOCK,b.db() as con:
            require(capture.source(con,task)==binding
                and capture.quality.digest(capture.enrollment.lookup(con,e['issue_id']))==identity['enrollment_sha256'])
            con.execute('INSERT INTO quality_snapshot_intents VALUES(?,?,?,?,?)',
                (task,json.dumps(identity,sort_keys=True),json.dumps(state,sort_keys=True),
                    capture.quality.digest(identity),capture.quality.digest(state)))
    if state['stage']=='prepared':
        require(b.docker('GET','/volumes/'+name) is None)
        state=save(b,task,identity,state,{**state,'stage':'volume_create_intent'})
        try:b.docker('POST','/volumes/create',dict(Name=name,Driver='local',Labels=labels))
        except TimeoutError:raise validation_job.Pending('observe exact snapshot volume; no repeated create') from None
    info=b.docker('GET','/volumes/'+name)
    if info is None:raise validation_job.Pending('observe snapshot volume creation; no repeated POST')
    observed=volume_identity(info,identity)
    if state['stage']=='volume_create_intent':
        state=save(b,task,identity,state,{**state,'stage':'copy_pending','volume_identity':observed})
    require(state['stage']=='copy_pending' and state['volume_identity']==observed)
    with b.db() as con:
        if maintenance.current(con):raise validation_job.Pending('maintenance pauses snapshot effects; preserve copy job')
        require(capture.source(con,task)==binding
            and capture.quality.digest(capture.enrollment.lookup(con,e['issue_id']))==identity['enrollment_sha256'])
        try:test_first_job.run(b,con,task,'copy',identity['payload'])
        except TimeoutError:raise validation_job.Pending('observe same immutable snapshot copy job') from None
        copied=capture.copy_record(b,con,e,plan,spec,task,binding)
    final=dict(stage='snapshot_copied',owner=e['author'],snapshot_volume=name,copy_job=task+':copy',
        manifest_sha256=copied['prepared']['manifest_sha256'],copy_sha256=capture.quality.digest(copied),
        volume_identity=observed,execution_authorized=False,delivery_approval=False)
    return save(b,task,identity,state,final)


def advance(b,task):
    """Coordinator entrypoint, not a worker tool or a native admission waiver."""
    capture.enrollment.canonical(task)
    with b.db() as con:
        capture.initialize(con)
        row=con.execute('SELECT state FROM quality_red_captures WHERE task_id=?',(task,)).fetchone()
        if maintenance.current(con) and (not row or json.loads(row[0])['stage']=='validation_pending'):
            raise validation_job.Pending('maintenance pauses new Red/copy effects')
    if not row:
        snapshot=prepare(b,task)
        if snapshot['stage']=='technical_blocked':return snapshot
    return capture.observe(b,task)
