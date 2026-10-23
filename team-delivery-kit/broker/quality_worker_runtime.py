"""Shared fixed worker/startup protocol for controller-owned v2 phase adapters.

Adapters are local modules, never supplied through worker/API arguments. Phase
authority, mounts and handlers remain adapter-specific. Unknown Docker/transport
outcomes retain the existing one-shot journal, without another execution.
"""
import hashlib
import json
import time
try:
    from . import controller_maintenance as maintenance, worker_creation_intent as intents
except ImportError:
    import controller_maintenance as maintenance, worker_creation_intent as intents


def require(value):
    if not value:
        raise ValueError('exact v2 worker authority and policy required')


def execute(b, token, args, streaming, defer_transport, adapter):
    adapter.enabled(b)
    require(args == {} and streaming is True and defer_transport is True)
    with b.db() as con:
        row = con.execute('SELECT * FROM grants WHERE digest=?',
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        require(row is not None and row['used'] == 0 and row['deadline'] > time.time())
        row = dict(row)
    request = row['request_id']
    require(adapter.owns(b, request))
    adapter.current(b, request)
    adapter.prepare_worker(b, request)
    expected = adapter.payload(b, request)
    adapter.current(b, request)  # Reauthenticate after slow prep/volume/image reads.
    name = b.PREFIX+'-job-'+request
    with b.LOCK, b.db() as con:
        maintenance.require_admission(con)
        stored = con.execute('SELECT * FROM grants WHERE request_id=?', (request,)).fetchone()
        require(stored is not None and dict(stored) == row and stored['used'] == 0
            and stored['deadline'] > time.time())
        context = adapter.load_admission(con, request)
        require(context is not None)
        require(not con.execute('SELECT 1 FROM leases WHERE request_id=?', (request,)).fetchone())
        require(con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0] < 2)
        require(not con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
            "WHERE n.agent_id=? AND l.status IN ('creating','starting','running','closing')",
            (context['agent_id'],)).fetchone())
        con.execute('UPDATE grants SET used=1 WHERE request_id=?', (request,))
        con.execute('INSERT INTO leases VALUES(?,?,?,?,?)',
            (request, 'acp-session', name, 'creating', time.time()+420))
        intents.record(con, request, expected)
    try:
        b.docker('POST', '/containers/create?name='+name, expected)
    except TimeoutError:
        with b.db() as con:
            intents.uncertain(con, request)
        raise
    except Exception:
        with b.db() as con:
            con.execute("UPDATE leases SET status='closing' WHERE request_id=?", (request,))
        raise
    adapter.current(b,request)  # Slow creation must not start a terminal native task.
    with b.db() as con:
        intents.start_intent(con, request)
    try:
        b.docker('POST', '/containers/'+name+'/start')
    except TimeoutError:
        with b.db() as con:
            intents.start_uncertain(con, request)
        raise
    except Exception:
        with b.db() as con:
            con.execute("UPDATE leases SET status='closing' WHERE request_id=?", (request,))
        raise
    with b.db() as con:
        intents.started(con, request)
        return dict(con.execute('SELECT * FROM leases WHERE request_id=?', (request,)).fetchone())


def open_transport(b, row, result, scope, adapter):
    adapter.enabled(b)
    request = row['request_id']
    binding = adapter.current(b, request)
    require(scope == binding['scope'])
    expected = adapter.payload(b, request)
    info = b.docker('GET', '/containers/'+result['name']+'/json')
    require(info is not None and not intents.policy_differences(expected, info)
        and info.get('State', {}).get('Status') == 'running')
    with b.LOCK, b.db() as con:
        row = con.execute('SELECT * FROM grants WHERE request_id=?', (request,)).fetchone()
        startup = con.execute('SELECT state FROM acp_startups WHERE request_id=?', (request,)).fetchone()
        lease = con.execute('SELECT * FROM leases WHERE request_id=?', (request,)).fetchone()
        original = con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?', (request,)).fetchone()
        observations = con.execute('SELECT receipt_sha256,receipt FROM worker_policy_observations '
            'WHERE request_id=?', (request,)).fetchall()
        require(row is not None and row['used'] == 1 and row['deadline'] > time.time()
            and startup is not None and json.loads(startup[0])['stage'] == 'transport_intent'
            and lease is not None and lease['status'] == 'running' and lease['deadline'] > time.time()
            and lease['name'] == result['name'] and original is not None and json.loads(original[0]) == expected)
        proofs = [json.loads(raw) for sha, raw in observations if hashlib.sha256(raw.encode()).hexdigest() == sha]
        require(any(p.get('container_id') == info['Id'] and p.get('worker_image') == expected['Image']
            and p.get('payload_sha256') == hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
            and p.get('docker_status') == 'running' and p.get('normalized_differences') == [] for p in proofs))
        con.execute('CREATE TABLE IF NOT EXISTS quality_transport_intents(request_id TEXT PRIMARY KEY,state TEXT)')
        require(not con.execute('SELECT 1 FROM quality_transport_intents WHERE request_id=?', (request,)).fetchone())
        con.execute('INSERT INTO quality_transport_intents VALUES(?,?)', (request, 'opening'))
    try:
        try:
            from acp_transport import Transport
        except ImportError:
            from broker.acp_transport import Transport
        session = Transport(b.docker, result['name'], persistent=False, **adapter.transport_spec(b, request))
    except Exception:
        with b.db() as con:
            con.execute("UPDATE quality_transport_intents SET state='outcome_unknown' WHERE request_id=?", (request,))
            con.execute("UPDATE leases SET status='closing' WHERE request_id=?", (request,))
        raise
    b.SESSIONS[request] = session
    with b.db() as con:
        con.execute("UPDATE quality_transport_intents SET state='opened' WHERE request_id=?", (request,))
    return result
