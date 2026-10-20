"""Operator-only, once-per-experiment recovery of late unused admission.

This is not a provider retry or a new DATA/author budget. The old native task,
expired grant and blocked state remain evidence; only CTO assessment is rearmed.
"""
import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from generic_harness_calibration import digest, require

RUNTIME_IMAGE='sha256:920ce7b26849c20aa5a315dc15f4dad2da7dd6af10a37e4568ba183f19a9c406'
SOURCE_HASHES={
    'broker.py':'03f2b0cd18dce00b0a9fba0098c6bd66ba1ba966da5e61790a2c9c8fd3f51e8b',
    'calibration_coordination.py':'51a9ec63580b48323998bb96758d838bddb3a16b0492b875088edb1588ff99be',
    'generic_calibration_workflow.py':'b14953c6e2548373381099f55cd4da3fc3c8c6d35991a8b0faefec982a28bdce',
    'maintained_test_calibration.py':'c575b5163ebedb3f27009b182e0b82745094f6de818a2ea40884e038a6e0165b',
    'acp_wrapper.py':'97548e5ae5ae702e0d3865d26e2b76aa7dc32d72dbe56b4d7bd5c11ea396d508',
}
EMPTY_TABLES=('leases','acp_startups','acp_events','tool_events','broker_errors')
FALSE_FLAGS=('source_reset','author_retry_authorized','execution_authorized','delivery_approval')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_admission_recoveries(recovery_id TEXT PRIMARY KEY,receipt TEXT)')


def qualified(con,key,cfg,state):
    initialize(con)
    row=con.execute('SELECT receipt FROM calibration_admission_recoveries WHERE recovery_id=?',(key,)).fetchone()
    require(row is not None);receipt=json.loads(row[0]);old=receipt['previous_state']
    require(receipt['config_sha256']==digest(cfg) and receipt['operation']=='late_unused_admission_recovery_v1'
        and receipt['infrastructure_attempt_limit']==1 and receipt['retry_budget_reset'] is False
        and state.get('admission_recovery_sha256')==digest(receipt)
        and all(receipt[k] is False and state.get(k) is False for k in FALSE_FLAGS)
        and all(state.get(k)==old.get(k) for k in ('issue_id','measurement','measurement_job','missing_reads')))
    return receipt


def transition(con,key,cfg,state,*,task,binding,grant,counts,installation,barrier,namespace,now=None):
    initialize(con);now=time.time() if now is None else now
    require(not con.execute('SELECT 1 FROM calibration_admission_recoveries WHERE recovery_id=?',(key,)).fetchone())
    current=con.execute('SELECT config,state FROM calibration_read_recoveries WHERE recovery_id=?',(key,)).fetchone()
    require(current and list(map(json.loads,current))==[cfg,state])
    require(barrier.get('stage')=='sealed' and barrier.get('drained') is True
        and barrier.get('namespace')==namespace and bool(barrier.get('operation_id')))
    require(state.get('stage')=='blocked' and state.get('category')=='dependency_evidence_rejected'
        and not state.get('admission_recovery_sha256') and not state.get('cto_decision')
        and all(state.get(k) is False for k in FALSE_FLAGS)
        and task.get('agent_id')==cfg['source']['cto'] and task.get('issue_id')==state['issue_id']
        and task.get('wakeup_id')==state['wakeup_id'] and task.get('status')=='failed'
        and task.get('error')=='hermes initialize failed: hermes process exited'
        and task.get('failure_reason')=='agent_error.process_failure')
    require(binding.get('task_id')==task['id'] and binding.get('agent_id')==task['agent_id']
        and binding.get('issue_id')==task['issue_id']
        and binding.get('scope','').split(':')[-2:]==['planning',task['id']]
        and grant.get('task_id')==task['id'] and grant.get('request_id')==binding.get('request_id')
        and grant.get('mode')=='planning' and type(grant.get('attempt')) is int and grant['attempt']==1
        and type(grant.get('used')) is int and grant['used']==0
        and set(counts)==set(EMPTY_TABLES) and all(type(v) is int and v==0 for v in counts.values()))
    require(installation.get('operation')=='installed_admission_isolation_v1'
        and installation.get('runtime_image')==RUNTIME_IMAGE and installation.get('source_hashes')==SOURCE_HASHES
        and installation.get('lock_isolation') is True and installation.get('shared_lane_lock') is True)
    # The pinned broker.py issues exactly time.time()+480. Do not infer an
    # issuance timestamp from a different controller version or grant lifetime.
    started=datetime.datetime.fromisoformat(task['started_at'].replace('Z','+00:00')).timestamp()
    completed=datetime.datetime.fromisoformat(task['completed_at'].replace('Z','+00:00')).timestamp()
    require(type(grant.get('deadline')) in (int,float))
    issued=grant['deadline']-480
    require(0<completed-started<=30 and issued-started>=15 and completed<issued<=completed+60
        and grant['deadline']<=now)
    receipt=dict(operation='late_unused_admission_recovery_v1',config_sha256=digest(cfg),previous_state=state,
        failed_task=task,expired_unused_grant=grant,binding=binding,empty_effect_counts=counts,
        admission_issued_at=issued,native_completed_at=completed,installation=installation,
        maintenance_operation=barrier['operation_id'],at=now,infrastructure_attempt_limit=1,
        retry_budget_reset=False,**{k:False for k in FALSE_FLAGS})
    updated=dict(state,stage='cto_dispatch',owner=cfg['source']['cto'],
        admission_recovery_sha256=digest(receipt),
        required_action='One CTO assessment after qualified late-admission repair; prior failure and all delivery gates retained')
    for field in ('wakeup_id','marker','phase_started','category'):updated.pop(field,None)
    con.execute('SAVEPOINT admission_recovery')
    try:
        con.execute('INSERT INTO calibration_admission_recoveries VALUES(?,?)',(key,json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE calibration_read_recoveries SET state=? WHERE recovery_id=?',
            (json.dumps(updated,sort_keys=True),key))
        con.execute('RELEASE SAVEPOINT admission_recovery')
    except Exception:
        con.execute('ROLLBACK TO SAVEPOINT admission_recovery');con.execute('RELEASE SAVEPOINT admission_recovery');raise
    return receipt


def installed(b):
    try:import calibration_coordination as coordination,generic_calibration_workflow as workflow,maintained_test_calibration as maintained
    except ImportError:from broker import calibration_coordination as coordination,generic_calibration_workflow as workflow,maintained_test_calibration as maintained
    require(coordination.LOCK is workflow.CALIBRATION_LOCK is maintained.CALIBRATION_LOCK)
    entered,release=threading.Event(),threading.Event()
    def hold():
        with coordination.LOCK:entered.set();release.wait(3)
    thread=threading.Thread(target=hold);thread.start()
    try:
        require(entered.wait(1));available=b.LOCK.acquire(timeout=.25)
        if available:b.LOCK.release()
        require(available)
    finally:release.set();thread.join(3)
    require(not thread.is_alive())
    hashes={name:hashlib.sha256(Path('/'+name).read_bytes()).hexdigest()
        for name in SOURCE_HASHES if name!='acp_wrapper.py'}
    runtime=b.docker('GET','/containers/'+b.PREFIX+'-runtime-1/json')
    require(runtime['Image']==RUNTIME_IMAGE and runtime['State']['Running'] is True
        and runtime['Config']['Labels']['com.docker.compose.project']==b.PREFIX
        and runtime['Config']['Labels']['com.docker.compose.service']=='runtime')
    script='import hashlib;from pathlib import Path;print(hashlib.sha256(Path("/opt/acp_wrapper.py").read_bytes()).hexdigest())'
    entry=b.docker('POST','/containers/'+runtime['Id']+'/exec',dict(AttachStdout=True,AttachStderr=False,Tty=True,Cmd=['python','-c',script]))
    conn=b.DockerConnection('localhost',timeout=10)
    try:
        conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),{'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(257)
        require(response.status==200 and len(raw)<=256)
    finally:conn.close()
    outcome=b.docker('GET','/exec/'+entry['Id']+'/json');require(not outcome['Running'] and outcome['ExitCode']==0)
    hashes['acp_wrapper.py']=raw.decode().strip()
    require(hashes==SOURCE_HASHES)
    return dict(operation='installed_admission_isolation_v1',runtime_image=runtime['Image'],source_hashes=hashes,
        lock_isolation=True,shared_lane_lock=True)


def recover(b,key,operation):
    try:import controller_maintenance as maintenance,calibration_read_recovery as lane,native,native_scope_note
    except ImportError:from broker import controller_maintenance as maintenance,calibration_read_recovery as lane,native,native_scope_note
    require(str(uuid.UUID(operation))==operation and len(key)==64 and all(c in '0123456789abcdef' for c in key))
    with b.db() as con:
        barrier=maintenance.current(con)
        require(barrier and barrier['operation_id']==operation and barrier['stage']=='sealed')
        row=con.execute('SELECT config,state FROM calibration_read_recoveries WHERE recovery_id=?',(key,)).fetchone()
        require(row is not None);cfg,state=map(json.loads,row)
        if state.get('admission_recovery_sha256'):return qualified(con,key,cfg,state)
    require(not maintenance.native_active(b))
    fx=lane.Effects(b);fx.verify(cfg)
    runs=fx.runs(cfg,state);matches=[t for t in runs if t.get('wakeup_id')==state['wakeup_id']]
    require(len(matches)==1);task=fx.source.plans.task(matches[0]['id'],cfg['source']['cto'])
    expected='DELIVERY_PLANNING_START '+state['marker']+'\nSource: '+cfg['source']['author_task']+'\n'+lane.instruction(cfg,state,'cto').strip()
    require(state['marker']==lane.dispatch_marker(cfg,state,'cto'))
    require(native_scope_note.canonical(task.get('handoff_note',''),state['wakeup_id'])==expected)
    proof=installed(b)
    require(not maintenance.native_active(b))
    with b.LOCK,b.db() as con:
        maintenance.transaction(con);barrier=maintenance.current(con)
        require(barrier and barrier['operation_id']==operation)
        require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
        bindings=con.execute('SELECT * FROM native_bindings WHERE task_id=?',(task['id'],)).fetchall()
        grants=con.execute('SELECT task_id,attempt,mode,request_id,deadline,used FROM grants WHERE task_id=?',(task['id'],)).fetchall()
        require(len(bindings)==len(grants)==1);binding,grant=dict(bindings[0]),dict(grants[0])
        counts={table:con.execute('SELECT count(*) FROM '+table+' WHERE request_id=?',(binding['request_id'],)).fetchone()[0]
            for table in EMPTY_TABLES}
        return transition(con,key,cfg,state,task=task,binding=binding,grant=grant,counts=counts,
            installation=proof,barrier=barrier,namespace=b.PREFIX)
