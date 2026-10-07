"""Durable worker bootstrap intents. Observation never starts or approves work."""
import hashlib,json,time
from pathlib import Path


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS worker_creation_intents(request_id TEXT PRIMARY KEY,payload TEXT,state TEXT)')


def record(con,request,payload):
    initialize(con)
    encoded=json.dumps(payload,sort_keys=True)
    old=con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
    if old and old[0]!=encoded:raise ValueError('immutable worker create intent required')
    if not old:con.execute('INSERT INTO worker_creation_intents VALUES (?,?,?)',
        (request,encoded,json.dumps(dict(stage='create_intent',at=time.time(),delivery_approval=False))))


def uncertain(con,request):
    con.execute('UPDATE worker_creation_intents SET state=? WHERE request_id=?',
        (json.dumps(dict(stage='create_outcome_unknown',at=time.time(),required_action='observe_exact_container_no_repost',delivery_approval=False)),request))


def start_intent(con,request):
    """Commit before POST start. An interrupted intention must not be replayed."""
    row=con.execute('SELECT state FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
    if not row or json.loads(row[0]).get('stage')!='create_intent':
        raise ValueError('fresh acknowledged creation required before start')
    con.execute('UPDATE worker_creation_intents SET state=? WHERE request_id=?',
        (json.dumps(dict(stage='start_intent',at=time.time(),required_action='observe_start_no_repost',delivery_approval=False)),request))


def start_uncertain(con,request):
    row=con.execute('SELECT state FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
    if not row or json.loads(row[0]).get('stage')!='start_intent':
        raise ValueError('durable start intent required')
    state=json.loads(row[0])
    con.execute('UPDATE worker_creation_intents SET state=? WHERE request_id=?',
        (json.dumps({**state,'stage':'start_outcome_unknown'}),request))


def started(con,request):
    row=con.execute('SELECT state FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
    if not row or json.loads(row[0]).get('stage')!='start_intent':
        raise ValueError('durable start intent required')
    con.execute('UPDATE worker_creation_intents SET state=? WHERE request_id=?',
        (json.dumps(dict(stage='start_acknowledged',at=time.time(),delivery_approval=False)),request))


def observe(payload,state,info,native_status,deadline,now):
    """A late acknowledgement is not permission to start a terminal task."""
    stage=state.get('stage')
    if stage not in ('create_intent','create_outcome_unknown','late_container_observed','start_intent','start_outcome_unknown','start_acknowledged','start_running_observed'):return state,None
    starting=stage in ('start_intent','start_outcome_unknown','start_acknowledged','start_running_observed')
    terminal=native_status in ('failed','completed','cancelled') or now>=deadline
    if info is None:
        action=('observe_late_start_even_after_native_termination' if terminal else 'observe_start_no_repost') if starting else (
            'observe_late_create_even_after_native_termination' if terminal else 'observe_exact_container_no_repost')
        return {**state,'required_action':action},'failed' if terminal else None
    cfg=info.get('Config',{});host=info.get('HostConfig',{})
    expected_env={v.split('=',1)[0]:v.split('=',1)[1] for v in payload.get('Env',[])}
    observed_env={v.split('=',1)[0]:v.split('=',1)[1] for v in cfg.get('Env',[]) if '=' in v}
    if (info.get('Image')!=payload['Image'] or any(cfg.get(k)!=payload.get(k) for k in ('User','Entrypoint','Cmd','NetworkDisabled'))
            or any(cfg.get('Labels',{}).get(k)!=v for k,v in payload['Labels'].items())
            or any(observed_env.get(k)!=v for k,v in expected_env.items())
            or any(host.get(k)!=v for k,v in payload['HostConfig'].items())):
        return {**state,'stage':'ownership_or_policy_conflict','required_action':'controller_audit_no_start_or_delete','delivery_approval':False},None
    fact=dict(container_id=info['Id'],docker_status=info['State']['Status'],
        started_at=info['State'].get('StartedAt'),native_status=native_status,
        payload_sha256=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())
    if starting:
        if terminal:
            return {**state,'stage':'late_start_observed','fact':fact,'owner':'controller',
                'required_action':'preserve_and_retire_terminal_bootstrap_container',
                'author_retry_authorized':False,'delivery_approval':False},'failed'
        if info['State']['Status']=='running':
            return {**state,'stage':'start_running_observed','fact':fact,'owner':'controller',
                'required_action':'qualify_current_capability_and_transport_before_ACP',
                'author_retry_authorized':False,'delivery_approval':False},None
        if info['State']['Status'] in ('exited','dead','removing'):
            return {**state,'stage':'bootstrap_stopped','fact':fact,'owner':'controller',
                'required_action':'diagnose_bootstrap_no_restart',
                'author_retry_authorized':False,'delivery_approval':False},'failed'
        return {**state,'fact':fact,'required_action':'observe_start_no_repost'},None
    return {**state,'stage':'late_container_observed','fact':fact,'owner':'controller',
        'required_action':'preserve_and_retire_terminal_bootstrap_container' if terminal else 'qualify_startup_readiness_before_ACP',
        'author_retry_authorized':False,'delivery_approval':False},'failed' if terminal else None


def reconcile(b):
    """Watchdog observation only; release capacity only on terminal authority."""
    with b.LOCK,b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='worker_creation_intents'").fetchone():return
        rows=con.execute("SELECT i.request_id,i.payload,i.state,l.name,l.deadline FROM worker_creation_intents i JOIN leases l USING(request_id)").fetchall()
    for request,raw_payload,raw_state,name,deadline in rows:
        state=json.loads(raw_state)
        if state.get('stage') not in ('create_intent','create_outcome_unknown','late_container_observed','start_intent','start_outcome_unknown','start_acknowledged','start_running_observed'):continue
        native_status=None
        with b.db() as con:
            present=con.execute("SELECT 1 FROM sqlite_master WHERE name='native_bindings'").fetchone()
            binding=con.execute('SELECT task_id,agent_id FROM native_bindings WHERE request_id=?',(request,)).fetchone() if present else None
        if binding:
            try:
                try:import native
                except ImportError:from broker import native
                native_status=native.task_record(json.loads((Path(b.STATE)/'native.json').read_text()),binding[0],binding[1])['status']
            except (OSError,ValueError,KeyError,RuntimeError):continue
        try:info=b.docker('GET','/containers/'+name+'/json')
        except (OSError,TimeoutError,RuntimeError):continue
        changed,lease=observe(json.loads(raw_payload),state,info,native_status,deadline,time.time())
        with b.LOCK,b.db() as con:
            current=con.execute('SELECT state FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
            if not current or current[0]!=raw_state:continue
            con.execute('UPDATE worker_creation_intents SET state=? WHERE request_id=?',(json.dumps(changed,sort_keys=True),request))
            if lease:con.execute("UPDATE leases SET status=? WHERE request_id=? AND status='creating'",(lease,request))
