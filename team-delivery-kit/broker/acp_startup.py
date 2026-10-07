"""Asynchronous ACP bootstrap for one consumed native capability.

Polling never issues a grant or repeats create/start. A durable transport intent
prevents silently opening a second transport after a controller restart.
"""
import hashlib
import json
from pathlib import Path
import threading
import time

LOCK=threading.RLock()
THREADS={}
STARTUP_SECONDS=90


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS acp_startups(request_id TEXT PRIMARY KEY,state TEXT)')


def authority(b,token):
    """Read-only current authority; consumed capabilities allow continuation only."""
    with b.db() as con:
        row=con.execute('SELECT * FROM grants WHERE digest=?',
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row['deadline']<=time.time():raise ValueError('invalid or expired startup capability')
        latest=con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(row['task_id'],)).fetchone()[0]
        if latest!=row['attempt']:raise ValueError('stale startup capability')
        binding=con.execute('SELECT * FROM native_bindings WHERE request_id=?',(row['request_id'],)).fetchone()
        if not binding:raise ValueError('startup requires native binding')
        row=dict(row);binding=dict(binding)
    try:import native
    except ImportError:from broker import native
    current=native.task_binding(json.loads((Path(b.STATE)/'native.json').read_text()),binding['task_id'],binding['agent_id'])
    if (current['scope']!=binding['scope'] or binding['task_id']!=row['task_id']
            or current['mode']!=row['mode'] or current['issue_id']!=binding['issue_id']):
        raise ValueError('native startup identity drift')
    return row,binding


def write(b,request,state):
    with b.db() as con:
        con.execute('UPDATE acp_startups SET state=? WHERE request_id=?',
            (json.dumps(state,sort_keys=True),request))


def request(b,token,payload,*,begin):
    if payload!={}:raise ValueError('startup parameters are controller-owned')
    row,_=authority(b,token)
    request_id=row['request_id']
    with LOCK,b.db() as con:
        initialize(con)
        saved=con.execute('SELECT state FROM acp_startups WHERE request_id=?',(request_id,)).fetchone()
        if not saved:
            if not begin:raise ValueError('startup not requested')
            if row['used']:raise ValueError('consumed capability has no startup intent')
            state=dict(stage='pending',deadline=min(row['deadline'],time.time()+STARTUP_SECONDS),
                required_action='observe_worker_startup',delivery_approval=False)
            con.execute('INSERT INTO acp_startups VALUES (?,?)',(request_id,json.dumps(state,sort_keys=True)))
            con.commit()
        else:state=json.loads(saved[0])
        if state['stage']=='ready':
            lease=con.execute('SELECT status,deadline FROM leases WHERE request_id=?',(request_id,)).fetchone()
            if request_id in b.SESSIONS and lease and lease[0]=='running' and lease[1]>time.time():
                return {**state['result'],'startup_status':'ready'}
            state={**state,'stage':'failed','category':'startup_transport_lost',
                'required_action':'diagnose_transport_no_silent_recreation'}
            con.execute('UPDATE acp_startups SET state=? WHERE request_id=?',(json.dumps(state,sort_keys=True),request_id))
        if state['stage'] in ('pending','transport_intent'):
            worker=THREADS.get(request_id)
            if not worker or not worker.is_alive():
                if state['stage']=='transport_intent':
                    # An intent is terminal for this process if the opening
                    # thread disappeared. Never replay an ambiguous exec.
                    state={**state,'stage':'failed','category':'startup_transport_outcome_unknown',
                        'required_action':'diagnose_transport_no_silent_recreation'}
                    con.execute('UPDATE acp_startups SET state=? WHERE request_id=?',(json.dumps(state,sort_keys=True),request_id))
                else:
                    worker=threading.Thread(target=run,args=(b,token,request_id,state),daemon=True)
                    THREADS[request_id]=worker
                    worker.start()
        return {'startup_status':'failed' if state['stage']=='failed' else 'pending',
            'request_id':request_id,'category':state.get('category'),
            'required_action':state['required_action'],'delivery_approval':False}


def advance_worker(b,row,binding):
    """Inspect identity before continuing the *same* creation, never recreate."""
    try:import worker_creation_intent as intents
    except ImportError:from broker import worker_creation_intent as intents
    request_id=row['request_id']
    with b.db() as con:
        lease=con.execute('SELECT * FROM leases WHERE request_id=?',(request_id,)).fetchone()
        intent=con.execute('SELECT payload,state FROM worker_creation_intents WHERE request_id=?',(request_id,)).fetchone()
    if not lease or not intent:raise ValueError('startup intent missing; no replay permitted')
    lease=dict(lease);payload=json.loads(intent[0]);state=json.loads(intent[1])
    if lease['status'] not in ('creating','running') or lease['deadline']<=time.time():
        raise ValueError('startup lease no longer active')
    try:info=b.docker('GET','/containers/'+lease['name']+'/json')
    except (b.DockerOperationTimeout,OSError):return None
    if not info:return None
    # Revalidate the complete recorded worker policy even when start was
    # acknowledged. A name or Docker running state alone is insufficient.
    proof,_=intents.observe(payload,{'stage':'create_outcome_unknown'},info,'running',lease['deadline'],time.time())
    if proof['stage']=='ownership_or_policy_conflict':raise ValueError('startup worker policy drift')
    docker_status=info['State']['Status'];stage=state['stage']
    if stage in ('create_intent','create_outcome_unknown','late_container_observed'):
        if docker_status!='created':raise ValueError('worker started without controller start intent')
        # Serialize with the watchdog and persist *before* the only POST start.
        with b.LOCK:
            b.assert_review_task_running(binding)
            with b.db() as con:
                current=con.execute('SELECT state FROM worker_creation_intents WHERE request_id=?',(request_id,)).fetchone()
                if current[0]!=intent[1]:return None
                grant=con.execute('SELECT * FROM grants WHERE request_id=?',(request_id,)).fetchone()
                latest=con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(row['task_id'],)).fetchone()[0]
                if not grant or not grant['used'] or grant['deadline']<=time.time() or latest!=row['attempt']:
                    raise ValueError('start authority no longer current')
                con.execute('UPDATE worker_creation_intents SET state=? WHERE request_id=?',
                    (json.dumps(dict(stage='start_intent',at=time.time(),required_action='observe_start_no_repost',delivery_approval=False)),request_id))
            try:b.docker('POST','/containers/'+lease['name']+'/start')
            except b.DockerOperationTimeout:
                with b.db() as con:intents.start_uncertain(con,request_id)
                return None
            with b.db() as con:intents.started(con,request_id)
        return None  # only a subsequent inspect can establish running
    if stage not in ('start_intent','start_outcome_unknown','start_acknowledged','start_running_observed'):
        raise ValueError('startup state requires diagnosis')
    if docker_status in ('exited','dead','removing'):raise ValueError('bootstrap worker stopped')
    if docker_status!='running':return None
    with b.db() as con:
        con.execute("UPDATE leases SET status='running' WHERE request_id=? AND status='creating'",(request_id,))
    return {**lease,'status':'running'}


def run(b,token,request_id,state):
    try:
        while time.time()<state['deadline']:
            try:row,binding=authority(b,token)
            except OSError:
                time.sleep(0.25);continue  # observation failure is not task termination
            if row['request_id']!=request_id:raise ValueError('startup identity changed')
            if not row['used']:
                try:b.execute_grant(token,{},streaming=True,defer_transport=True)
                except b.DockerOperationTimeout as error:
                    if error.operation not in ('containers_create','containers_start'):raise
                continue
            result=advance_worker(b,row,binding)
            if result:
                row,binding=authority(b,token)
                if time.time()>=state['deadline']:raise TimeoutError('startup deadline')
                write(b,request_id,{**state,'stage':'transport_intent',
                    'required_action':'observe_single_transport_open'})
                with b.LOCK:
                    row,binding=authority(b,token)
                    result=b.open_granted_transport(row,result,binding['scope'])
                authority(b,token)  # terminal native tasks cannot become ready
                write(b,request_id,{**state,'stage':'ready','result':result,
                    'required_action':'forward_actual_ACP_initialize'})
                return
            time.sleep(0.25)
        raise TimeoutError('startup deadline')
    except Exception as error:
        if request_id:
            category='startup_deadline' if isinstance(error,TimeoutError) else 'startup_'+b.failure_category(error)
            write(b,request_id,{**state,'stage':'failed','category':category,
                'required_action':'diagnose_bootstrap_no_identical_retry','delivery_approval':False})
            with b.db() as con:
                con.execute('INSERT INTO broker_errors VALUES (?,?,?,?)',(request_id,'acp_startup',category,time.time()))
    finally:
        with LOCK:
            if THREADS.get(request_id) is threading.current_thread():THREADS.pop(request_id,None)
