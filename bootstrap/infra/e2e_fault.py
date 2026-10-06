"""One explicit failure injection, restricted to a verified rehearsal worker."""
import json
import os
from pathlib import Path
import signal
import time
import subprocess
import sys


def identity(pid):
    proc=Path('/proc')/str(pid)
    try: raw=(proc/'environ').read_bytes()
    except PermissionError:
        # Read as the worker owner, without adding SYS_PTRACE or broad privileges.
        if os.geteuid()!=0 or proc.stat().st_uid!=10000: raise
        raw=subprocess.check_output([sys.executable,'-c','import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())',str(proc/'environ')],user=10000,group=10000,timeout=5)
    env=dict(item.split(b'=',1) for item in raw.split(b'\0') if b'=' in item)
    # comm may contain spaces/parentheses; fields after the final ')' start at 3.
    start=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
    return env,start


def tick(conn,config,store,now):
    from host_recovery import tick as recover_host
    recovered=recover_host(conn,config,store,now)
    if recovered: return recovered
    path=config['db_path'].with_name('e2e.json')
    if not path.exists(): return []
    data=json.loads(path.read_text())
    if data.get('attempt')!=config['attempt'] or not data.get('inject_worker_failure'): return []
    key='green-worker-interruption'
    old=store.get(config['attempt'],'e2e_fault',key)
    if old and old.get('state') in ('killed','closed'): return []
    task=conn.execute('SELECT * FROM tasks WHERE id=?',(data['cards']['build'],)).fetchone()
    if not task or task['status']!='running' or not task['worker_pid']: return []
    root=config['db_path'].parent/'workspaces'/task['id']; marker=root/'e2e-fault-ready.json'
    if not marker.exists() or marker.is_symlink(): return []
    value=json.loads(marker.read_text())
    if any(value.get(k)!=v for k,v in dict(task=task['id'],run=task['current_run_id'],claim=task['claim_lock']).items()) or not isinstance(value.get('green_run'),int): return []
    pid=task['worker_pid']
    try: env,start=identity(pid)
    except (FileNotFoundError,ProcessLookupError): return []
    expected={b'HERMES_KANBAN_TASK':task['id'].encode(),b'HERMES_KANBAN_RUN_ID':str(task['current_run_id']).encode(),b'HERMES_KANBAN_CLAIM_LOCK':task['claim_lock'].encode()}
    if any(env.get(k)!=v for k,v in expected.items()): raise PermissionError('failure probe refused: PID identity mismatch')
    record=dict(state='intent',task=task['id'],run=task['current_run_id'],pid=pid,start=start,created_at=now)
    if old and any(old.get(k)!=record[k] for k in ('task','run','pid','start')): return []
    if old: record.update(old)
    if data.get('inject_supervisor_restart') and not record.get('restart_requested'):
        record.update(restart_requested=True,observer_pid=os.getpid())
        with store.transaction(config['attempt']): store._put(config['attempt'],'e2e_fault',key,record)
        print('E2E: restarting observer after durable injection intent, before side effect',flush=True)
        os._exit(75)
    if record.get('restart_requested'):
        record['observer_restart_observed']=record.get('observer_pid')!=os.getpid()
    with store.transaction(config['attempt']): store._put(config['attempt'],'e2e_fault',key,record)
    # This journal is committed before kill; a restart may only revisit the
    # exact process identity, never a newly claimed worker or a reused PID.
    env2,start2=identity(pid)
    if start2!=start or any(env2.get(k)!=v for k,v in expected.items()): raise PermissionError('worker changed before injection')
    os.kill(pid,signal.SIGKILL)
    record.update(state='killed',signal='SIGKILL',killed_at=time.time())
    with store.transaction(config['attempt']): store._put(config['attempt'],'e2e_fault',key,record)
    return [f"🧪 {task['id']}: falha controlada aplicada ao run {task['current_run_id']}; workspace preservado. Aguardando recuperação nativa, sem intervenção do CEO."]
