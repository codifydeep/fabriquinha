"""Operator-only drain/seal barrier; never replay grants or manufacture results.

There is deliberately no worker HTTP endpoint. Draining pauses new reconciliation
cycles but allows existing native tasks to obtain their ordinary grants and finish.
Sealing additionally refuses new grants; close/receipt operations remain available.
The barrier survives restarts and is released only by its original operation ID.
"""
import json
import re
import time
import threading
import urllib.request
import uuid

_cycle_ids = {}


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS controller_maintenance('
                'operation_id TEXT PRIMARY KEY, stage TEXT, receipt TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS controller_maintenance_cycles('
                'cycle_id TEXT PRIMARY KEY, namespace TEXT, stage TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS controller_cycle_owners(cycle_id TEXT PRIMARY KEY,identity TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS controller_cycle_interruptions(cycle_id TEXT PRIMARY KEY,receipt TEXT)')


def transaction(con):
    initialize(con)
    if not con.in_transaction: con.execute('BEGIN IMMEDIATE')


def current(con):
    initialize(con)
    rows = con.execute("SELECT receipt FROM controller_maintenance WHERE stage IN ('draining','sealed')").fetchall()
    if len(rows) > 1: raise ValueError('ambiguous controller maintenance')
    return json.loads(rows[0][0]) if rows else None


def require_admission(con):
    transaction(con)  # Grants and sealing serialize across separate processes.
    state = current(con)
    if state and state['stage'] == 'sealed': raise ValueError('controller maintenance sealed; no new grants')


def begin_cycle(b):
    with b.db() as con:
        if current(con):return False
    owner=cycle_owner(b)
    with b.LOCK, b.db() as con:
        transaction(con)
        if current(con): return False
        cycle = str(uuid.uuid4())
        con.execute('INSERT INTO controller_maintenance_cycles VALUES(?,?,?)',
                    (cycle, b.PREFIX, 'active'))
        if owner is not None:
            con.execute('INSERT INTO controller_cycle_owners VALUES(?,?)',(cycle,json.dumps(owner,sort_keys=True)))
        _cycle_ids.setdefault((b.PREFIX, threading.get_ident()), []).append(cycle)
        return True


def cycle_owner(b):
    # Minimal test adapters may lack Docker. Such legacy/unqualified ownership
    # never gains automatic orphan recovery; end_cycle still works normally.
    if not hasattr(b,'docker'):return None
    info=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')
    labels=(info or {}).get('Config',{}).get('Labels',{});state=(info or {}).get('State',{})
    if (not re.fullmatch('[a-f0-9]{64}',(info or {}).get('Id','')) or state.get('Running') is not True
            or not isinstance(state.get('StartedAt'),str) or not state['StartedAt']
            or labels.get('com.docker.compose.project')!=b.PREFIX or labels.get('com.docker.compose.service')!='execution-broker'):
        raise ValueError('current controller process identity required')
    return dict(container_id=info['Id'],started_at=state['StartedAt'])


def interrupt_verified_orphans(b,con):
    if not hasattr(b,'docker'):return
    rows=con.execute("SELECT c.cycle_id,o.identity FROM controller_maintenance_cycles c JOIN controller_cycle_owners o "
        "USING(cycle_id) WHERE c.namespace=? AND c.stage='active'",(b.PREFIX,)).fetchall()
    for cycle,raw in rows:
        owner=json.loads(raw)
        if (set(owner)!={'container_id','started_at'} or not re.fullmatch('[a-f0-9]{64}',owner['container_id'])
                or not isinstance(owner['started_at'],str) or not owner['started_at']):
            raise ValueError('invalid persisted cycle owner')
        try:info=b.docker('GET','/containers/'+owner['container_id']+'/json')
        except (TimeoutError,RuntimeError,OSError):continue  # Unknown is not dead.
        observation=dict(exists=info is not None)
        if info is not None:
            labels=info.get('Config',{}).get('Labels',{});state=info.get('State',{})
            if (info.get('Id')!=owner['container_id'] or labels.get('com.docker.compose.project')!=b.PREFIX
                    or labels.get('com.docker.compose.service')!='execution-broker'
                    or type(state.get('Running')) is not bool or not isinstance(state.get('StartedAt'),str)):
                continue
            if state['Running'] and state['StartedAt']==owner['started_at']:continue
            observation.update(container_id=info['Id'],running=state['Running'],started_at=state['StartedAt'])
        proof=dict(operation='interrupted_controller_cycle_v1',cycle_id=cycle,namespace=b.PREFIX,
            owner=owner,observation=observation,cycle_completed=False,source_reset=False,
            grants_replayed=False,delivery_approval=False)
        con.execute('INSERT INTO controller_cycle_interruptions VALUES(?,?)',(cycle,json.dumps(proof,sort_keys=True)))
        con.execute("UPDATE controller_maintenance_cycles SET stage='interrupted' WHERE cycle_id=? AND stage='active'",(cycle,))


def end_cycle(b):
    with b.LOCK, b.db() as con:
        transaction(con)
        stack = _cycle_ids.get((b.PREFIX, threading.get_ident()), [])
        if not stack: raise ValueError('maintenance cycle accounting mismatch')
        cycle = stack[-1]
        row = con.execute('SELECT namespace,stage FROM controller_maintenance_cycles WHERE cycle_id=?', (cycle,)).fetchone()
        if not row or tuple(row) != (b.PREFIX, 'active'): raise ValueError('exact active cycle required')
        con.execute("UPDATE controller_maintenance_cycles SET stage='completed' WHERE cycle_id=?", (cycle,))
        stack.pop()


def begin(b, operation):
    if str(uuid.UUID(operation)) != operation: raise ValueError('canonical maintenance operation required')
    with b.LOCK, b.db() as con:
        transaction(con)
        state = current(con)
        if state:
            if state['operation_id'] != operation: raise ValueError('another maintenance operation is active')
            return state
        if con.execute('SELECT 1 FROM controller_maintenance WHERE operation_id=?', (operation,)).fetchone():
            raise ValueError('completed maintenance identity cannot be reused')
        state = dict(operation_id=operation, stage='draining', started_at=time.time(),
                     namespace=b.PREFIX, delivery_approval=False, grants_replayed=False)
        con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                    (operation, state['stage'], json.dumps(state, sort_keys=True)))
        return state


def native_active(b):
    settings = json.loads((b.STATE / 'native.json').read_text())
    active = []
    for actor in settings['agents']:
        request = urllib.request.Request('http://backend:8080/api/agents/' + actor + '/tasks',
            headers={'Authorization': 'Bearer ' + settings['token'], 'X-Workspace-ID': settings['workspace_id']})
        with urllib.request.urlopen(request, timeout=5) as response: tasks = json.load(response)
        if not isinstance(tasks, list): raise ValueError('complete native task inventory required')
        for task in tasks:
            if (not isinstance(task, dict) or task.get('agent_id') != actor
                    or not task.get('workspace_id') or not task.get('runtime_id') or not task.get('status')):
                raise ValueError('complete owned native task metadata required')
            if task.get('workspace_id') != settings['workspace_id'] or task.get('runtime_id') != settings['runtime_id']:
                continue
            if task.get('status') not in ('completed', 'failed', 'cancelled', 'canceled'):
                active.append(task['id'])
    return sorted(set(active))


def seal(b, operation):
    # Read-only native inventory before acquiring the broker lock. Queued native
    # work is not invisible merely because it has not obtained a lease yet.
    active = native_active(b)
    with b.LOCK, b.db() as con:
        transaction(con)
        state = current(con)
        if not state or state['operation_id'] != operation or state['namespace'] != b.PREFIX:
            raise ValueError('exact current maintenance operation required')
        if state['stage'] == 'sealed': return state
        interrupt_verified_orphans(b,con)
        leases = con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
        launching = con.execute('SELECT count(*) FROM grants g LEFT JOIN leases l USING(request_id) '
            'WHERE g.used=1 AND g.deadline>? AND l.request_id IS NULL', (time.time(),)).fetchone()[0]
        cycles = con.execute("SELECT count(*) FROM controller_maintenance_cycles WHERE namespace=? AND stage='active'", (b.PREFIX,)).fetchone()[0]
        if active or leases or cycles or launching:
            return {**state, 'drained': False, 'native_active': len(active), 'active_leases': leases,
                    'active_cycles': cycles, 'launching_grants': launching}
        state = {**state, 'stage': 'sealed', 'sealed_at': time.time(), 'drained': True}
        con.execute('UPDATE controller_maintenance SET stage=?,receipt=? WHERE operation_id=?',
                    ('sealed', json.dumps(state, sort_keys=True), operation))
        return state


def release(b, operation):
    with b.LOCK, b.db() as con:
        transaction(con)
        state = current(con)
        if not state or state['operation_id'] != operation or state['stage'] != 'sealed' or state['namespace'] != b.PREFIX:
            raise ValueError('exact sealed maintenance operation required')
        state = {**state, 'stage': 'released', 'released_at': time.time()}
        con.execute('UPDATE controller_maintenance SET stage=?,receipt=? WHERE operation_id=?',
                    ('released', json.dumps(state, sort_keys=True), operation))
        return state
