"""Bounded requeue of only a structured local-host receipt block. Never approves."""
import json
import socket
from incident_supervisor import cli

def readiness():
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(10); s.connect('/run/review-control/controller.sock')
        s.sendall(b'{"operation":"e2e_host_readiness"}\n')
        with s.makefile('rb') as stream: return json.loads(stream.readline(65536))

def tick(conn,config,store,now):
    path=config['db_path'].with_name('e2e.json')
    if not path.exists(): return []
    data=json.loads(path.read_text())
    if data['attempt']!=config['attempt']: return []
    if not data['cards'].get('deploy'): return []
    task=conn.execute('SELECT * FROM tasks WHERE id=?',(data['cards']['deploy'],)).fetchone()
    if not task or task['status']!='blocked' or task['current_run_id'] is not None: return []
    event=conn.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(task['id'],)).fetchone()
    if not event: return []
    try: reason=json.loads(json.loads(event['payload'])['reason'])
    except (KeyError,TypeError,ValueError): return []
    if reason.get('category')!='host_receipt_pending': return []
    key=task['id']; old=store.get(config['attempt'],'host_recovery',key) or {}
    if old.get('event')==event['id'] or old.get('count',0)>=2: return []
    proof=readiness()
    if not proof.get('ready') or proof.get('commit')!=reason.get('expected_commit') or proof.get('receipt_at',0)<=reason.get('at',0): return []
    record=dict(event=event['id'],count=old.get('count',0)+1,state='intent',proof=proof,at=now)
    with store.transaction(config['attempt']): store._put(config['attempt'],'host_recovery',key,record)
    cli(config,'unblock',key)
    record['state']='requeued'
    with store.transaction(config['attempt']): store._put(config['attempt'],'host_recovery',key,record)
    return [f"▶ {key}: recibo local novo verificado; deploy retomado sem aprovação automática. Tentativa {record['count']}/2."]
