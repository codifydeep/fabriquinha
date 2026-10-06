"""Once-per-issue recovery diagnosis for a host interruption, never author retry."""
import hashlib
import json
import time
import urllib.request
import uuid
try:
    import handoffs, native, handoff_runtime
except ImportError:
    from broker import handoffs, native, handoff_runtime


def qualified(con, issue, source, data):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='host_restart_recoveries'").fetchone():
        return False
    row = con.execute('SELECT receipt FROM host_restart_recoveries WHERE issue_id=?', (issue,)).fetchone()
    return bool(row and json.loads(row[0]) == data.get('host_restart_recovery')
                and json.loads(row[0])['request']['source_task'] == source)


def preserve(b, issue, task, scope, *, frozen_hashes=None):
    base = handoff_runtime.task_base(b, issue, task)
    work = b.PREFIX + '-work-' + hashlib.sha256(scope.encode()).hexdigest()[:32]
    info = b.docker('GET', '/volumes/' + work)
    if not info or info['Labels'].get('delivery-kit.owner') != b.OWNER or info['Labels'].get('delivery-kit.scope') != scope:
        raise ValueError('exact owned interrupted workspace required')
    volume = b.PREFIX + '-restart-snapshot-' + task
    labels = {'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': task,
              'delivery-kit.diagnostic-only': 'true'}
    old = b.docker('GET', '/volumes/' + volume)
    if old and old.get('Labels') != labels:
        raise ValueError('restart volume ownership drift')
    b.docker('POST', '/volumes/create', {'Name': volume, 'Labels': labels})
    name = b.PREFIX + '-restart-proof-' + uuid.uuid4().hex[:12]
    # Script is trusted controller code, not an agent-provided shell command.
    from pathlib import Path
    script = Path(__file__).with_name('worker_interruption_snapshot.py' if frozen_hashes is not None
                                    else 'host_restart_snapshot.py').read_text()
    controller = b.docker('GET', '/containers/' + b.PREFIX + '-execution-broker-1/json')
    if (not controller['State']['Running']
            or controller['Config']['Labels'].get('com.docker.compose.project') != b.PREFIX):
        raise ValueError('installed owned controller image required')
    # The preservation job requires controller validation modules, not the
    # deliberately smaller agent worker image.
    b.docker('POST', '/containers/create?name=' + name, dict(Image=controller['Image'],
        User='10000:10000', Entrypoint=['python'], Cmd=['-c', script], WorkingDir='/', NetworkDisabled=True,
        **({'Env': ['DELIVERY_FROZEN_HASHES_JSON=' + json.dumps(frozen_hashes, sort_keys=True)]}
           if frozen_hashes is not None else {}),
        Labels=labels, HostConfig=dict(ReadonlyRootfs=True, NetworkMode='none',
            CapDrop=['ALL'], SecurityOpt=['no-new-privileges'], Memory=134217728, PidsLimit=16,
            AutoRemove=False, Mounts=[dict(Type='volume',Source=work,Target='/workspace',ReadOnly=True),
                dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=volume,Target='/snapshot')])) )
    b.docker('POST', '/containers/' + name + '/start')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = b.docker('GET', '/containers/' + name + '/json')
        if not job['State']['Running']:
            if job['State']['ExitCode'] != 0:
                raise ValueError('restart preservation rejected; retain diagnostic job')
            proof = json.loads(b.docker_stdout(name, limit=2048))
            # Evidence retained in the snapshot; remove only this owned stopped job.
            current = b.docker('GET', '/containers/' + job['Id'] + '/json')
            if (current['State']['Running'] or current['Config']['Labels'].get('delivery-kit.source-task') != task
                    or current['Config']['Labels'].get('delivery-kit.owner') != b.OWNER):
                raise ValueError('restart cleanup identity drift')
            try:
                b.docker('DELETE', '/containers/' + job['Id'])
            except Exception:
                if b.docker('GET', '/containers/' + job['Id'] + '/json'):
                    raise RuntimeError('restart cleanup acknowledgment uncertain')
            return dict(proof, volume=volume, interrupted_task=task)
        time.sleep(.2)
    raise TimeoutError('restart preservation deadline; job retained')


def register(b, payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id','source_task','interrupted_task'}:
        raise ValueError('exact host interruption identity required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid restart identity')
    issue, source, interrupted = (payload[k] for k in ('issue_id','source_task','interrupted_task'))
    with b.LOCK:
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS host_restart_recoveries(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            previous = con.execute('SELECT receipt FROM host_restart_recoveries WHERE issue_id=?',(issue,)).fetchone()
            if previous:
                receipt = json.loads(previous[0])
                if receipt['request'] != payload:
                    raise ValueError('host recovery already consumed')
                return receipt
            row = handoffs.load(con, source)
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            if not row or row['issue_id'] != issue or row['stage'] != 'test_first_blocked':
                raise ValueError('blocked tests-only source required')
            data = json.loads(row['data'])
            if (data.get('error') != 'test_first_correction_failed_after_cto_diagnosis'
                    or not route.get('enabled') or not route.get('test_first') or route['author']==route['cto']):
                raise ValueError('independent blocked tests-only route required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone():
                raise ValueError('restart recovery cannot invalidate Red')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle restart recovery required')
            if con.execute('SELECT 1 FROM native_bindings WHERE task_id=?',(source,)).fetchone():
                raise ValueError('latest pre-admission failure required')
            bindings = con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(interrupted,)).fetchall()
            if len(bindings)!=1 or bindings[0]['status']!='interrupted' or bindings[0]['agent_id']!=route['author']:
                raise ValueError('exact interrupted author lease required')
            binding = dict(bindings[0])
            if con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(binding['request_id'],)).fetchone()[0]:
                raise ValueError('pre-tool interruption only')
        settings = json.loads((b.STATE/'native.json').read_text())
        runs = native.issue_task_runs(settings, issue)
        authors = sorted([r for r in runs if r.get('agent_id')==route['author']],key=lambda r:(r.get('created_at') or '',r['id']))
        if (len(authors)<2 or [r['id'] for r in authors[-2:]] != [interrupted,source]
                or authors[-1].get('status')!='failed' or authors[-1].get('error')!='hermes initialize failed: hermes process exited'
                or authors[-2].get('status')!='failed' or authors[-2].get('error')!='daemon restarted while task was in flight'
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('exact idle restart failure sequence required')
        with urllib.request.urlopen('http://model-proxy:8080/status',timeout=5) as response:
            health=json.loads(response.read(2048))
        if health.get('remaining',0)<route['minimum_calls']:
            raise ValueError('bounded model reserve required')
        proof = preserve(b, issue, interrupted, binding['scope'])
        if proof.get('baseline_unchanged') is not True or proof.get('red_verified') is not False:
            raise ValueError('verified diagnostic preservation required')
        receipt = dict(request=payload, proof=proof, previous_blocker=data,
            worker_image=b.IMAGE, author_retry_authorized=False, delivery_approval=False, at=time.time())
        updated = dict(data,host_restart_recovery=receipt,error='host_restart_diagnosis_required',
            diagnostic=dict(kind='verified_host_interruption',interrupted_task=interrupted,
                latest_task=source,baseline_unchanged=True,manifest_sha256=proof['manifest_sha256']))
        with b.db() as con:
            if dict(handoffs.load(con,source))!=dict(row):
                raise ValueError('restart blocker changed during qualification')
            con.execute('INSERT INTO host_restart_recoveries VALUES (?,?)',(issue,json.dumps(receipt,sort_keys=True)))
            handoffs.save(con,source,issue,'technical_decision_required',route['cto'],updated,time.time())
        return receipt
