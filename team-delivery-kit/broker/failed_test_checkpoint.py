"""Controller-only salvage of immutable tests, never of a native task status.

One attempt per execution. Genuine controller Red and the existing independent
test-review gate remain mandatory before product edits may be dispatched.
"""
import hashlib
import json
import time
import uuid

try:
    import native, handoffs
except ImportError:
    from broker import native, handoffs


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS failed_test_checkpoints('
                'issue_id TEXT PRIMARY KEY,source_task TEXT UNIQUE,receipt TEXT)')
    # Retain the original issue-level ledger unchanged for audit/rollback.
    # Its rejected old execution must not veto a later authenticated artifact.
    con.execute('CREATE TABLE IF NOT EXISTS failed_test_checkpoint_executions('
                'issue_id TEXT,source_task TEXT UNIQUE,receipt TEXT,PRIMARY KEY(issue_id,source_task))')
    con.execute('INSERT OR IGNORE INTO failed_test_checkpoint_executions '
                'SELECT issue_id,source_task,receipt FROM failed_test_checkpoints')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def eligible(route, source, runs):
    authors = [r for r in runs if r.get('agent_id') == route.get('author')]
    return (route.get('enabled') is True and route.get('test_first') is True
            and bool(route.get('techlead')) and route['techlead'] != route.get('author')
            and bool(route.get('test_first_files')) and source.get('status') == 'failed'
            and source.get('issue_id') == route.get('issue_id')
            and source.get('agent_id') == route.get('author') and bool(authors)
            and max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] == source['id']
            and not any(r.get('status') in ('queued', 'dispatched', 'running') for r in runs))


def proof(con, issue, task):
    initialize(con)
    row = con.execute('SELECT receipt FROM failed_test_checkpoint_executions WHERE issue_id=? AND source_task=?',
                      (issue, task)).fetchone()
    return json.loads(row[0]) if row else None


def validate_capture(b, con, row, supplied, route):
    """A private keyword is insufficient: require an exact durable controller intent."""
    saved = proof(con, row['issue_id'], supplied.get('source_task'))
    if (not saved or saved != supplied or saved.get('status') != 'capturing'
            or saved.get('operation') != 'failed_test_checkpoint_v1'
            or saved.get('route_sha256') != digest(route)
            or saved.get('scope') != row['scope'] or saved.get('request_id') != row['request_id']
            or saved.get('native_task_completed') is not False
            or saved.get('delivery_approved') is not False):
        raise ValueError('durable failed-test checkpoint intent required')
    frozen = con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',
                         (saved['source_task'],)).fetchone()
    if not frozen or frozen['status'] != 'complete' or frozen['volume'] != saved['snapshot_volume']:
        raise ValueError('failed-test immutable snapshot missing')
    volume = b.docker('GET', '/volumes/' + saved['snapshot_volume'])
    labels = volume.get('Labels', {}) if volume else {}
    if (labels.get('delivery-kit.owner') != b.OWNER
            or labels.get('delivery-kit.source-task') != saved['source_task']):
        raise ValueError('failed-test snapshot ownership drift')
    return saved['snapshot_volume']


def qualified(con, issue, task, red):
    saved = proof(con, issue, task)
    return bool(saved and saved.get('status') == 'red_captured'
                and saved.get('native_task_completed') is False
                and saved.get('delivery_approved') is False
                and saved.get('red_receipt_sha256') == digest(red)
                and red.get('task_id') == task and red.get('issue_id') == issue)


def capture(b, issue, task):
    for identifier in (issue, task):
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError('canonical checkpoint identity required')
    with b.LOCK:
        settings = json.loads((b.STATE / 'native.json').read_text())
        with b.db() as con:
            initialize(con)
            existing = con.execute('SELECT source_task,receipt FROM failed_test_checkpoint_executions '
                                   'WHERE issue_id=? AND source_task=?', (issue, task)).fetchone()
            saved = json.loads(existing['receipt']) if existing else None
            if saved and saved['status'] in ('rejected', 'red_captured'):
                return saved
            configured = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
            route = json.loads(configured[0]) if configured else {}
            row = con.execute('SELECT n.issue_id,n.request_id,n.agent_id,n.scope,g.mode,l.status '
                'FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
                'WHERE n.task_id=? ORDER BY g.attempt DESC LIMIT 1', (task,)).fetchone()
            existing_red = con.execute('SELECT task_id FROM test_first_red WHERE issue_id=?', (issue,)).fetchone()
            if (not row or row['issue_id'] != issue or not route.get('author')
                    or row['mode'] != 'implementation' or row['status'] != 'closed'
                    or (existing_red and (not saved or existing_red[0] != task))
                    or con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                        "WHERE n.issue_id=? AND l.status IN ('creating','starting','running','closing')", (issue,)).fetchone()):
                return None
        runs = native.issue_task_runs(settings, issue)
        source = native.task_record(settings, task, route.get('author'))
        if source.get('id') != task or not eligible(route, source, runs):
            return None
        with b.db() as con:
            prior_handoff = handoffs.load(con, task)
            saved = saved or dict(operation='failed_test_checkpoint_v1', status='freezing',
                issue_id=issue, source_task=task, scope=row['scope'], request_id=row['request_id'],
                route_sha256=digest(route), snapshot_volume=None,
                prior_handoff=dict(prior_handoff) if prior_handoff else None,
                native_task_completed=False, delivery_approved=False, at=time.time())
            if saved['route_sha256'] != digest(route):
                raise ValueError('failed-test checkpoint source drift')
            con.execute('INSERT OR IGNORE INTO failed_test_checkpoint_executions VALUES (?,?,?)',
                        (issue, task, json.dumps(saved, sort_keys=True)))
        try:
            snapshot = b.snapshot_submission({'task_id': task}, diagnostic=True)
            if saved['snapshot_volume'] not in (None, snapshot['volume']):
                raise ValueError('failed-test checkpoint snapshot drift')
            saved.update(status='capturing', snapshot_volume=snapshot['volume'])
            with b.db() as con:
                con.execute('UPDATE failed_test_checkpoint_executions SET receipt=? WHERE issue_id=? AND source_task=?',
                            (json.dumps(saved, sort_keys=True), issue, task))
            red = b.capture_test_first_red({'task_id': task}, _failed_checkpoint=saved)
        except TimeoutError as error:
            # The durable copy/calibration/Red intent observes its exact job.
            # A transport timeout is not a semantic rejection of the artifact.
            saved.update(status='capturing',observation_pending=True,
                         observation_category=type(error).__name__)
        except Exception as error:
            # No retry loop, raw exception/output, automatic approval or author wakeup.
            saved.update(status='rejected', failure_type=type(error).__name__,
                         failure_sha256=hashlib.sha256(str(error).encode()).hexdigest())
        else:
            saved.update(status='red_captured', red_receipt_sha256=digest(red))
        with b.db() as con:
            con.execute('UPDATE failed_test_checkpoint_executions SET receipt=? WHERE issue_id=? AND source_task=?',
                        (json.dumps(saved, sort_keys=True), issue, task))
        return saved


def resume_timeout(b,task):
    """Maintenance-only migration of a legacy rejected observation, not a worker retry."""
    try:import controller_maintenance as maintenance
    except ImportError:from broker import controller_maintenance as maintenance
    with b.LOCK,b.db() as con:
        barrier=maintenance.current(con)
        if not barrier or barrier.get('stage')!='sealed' or barrier.get('drained') is not True:
            raise ValueError('sealed drained maintenance required')
        row=con.execute('SELECT issue_id,receipt FROM failed_test_checkpoint_executions WHERE source_task=?',(task,)).fetchone()
        if not row:raise ValueError('exact failed checkpoint required')
        issue,saved=row[0],json.loads(row[1])
        if saved.get('timeout_observation_recovery'):return saved
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        if (saved.get('status')!='rejected' or saved.get('failure_type') not in ('DockerOperationTimeout','TimeoutError')
                or saved.get('route_sha256')!=digest(route) or not route.get('enabled')
                or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
            raise ValueError('idle exact legacy transport timeout required')
        snap=con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(task,)).fetchone()
        if not snap or snap['status']!='complete' or snap['volume']!=saved.get('snapshot_volume'):
            raise ValueError('preserved failed snapshot required')
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='test_first_jobs'").fetchone() and \
                con.execute('SELECT 1 FROM test_first_jobs WHERE job_key IN (?,?)',(task+':copy',task+':red')).fetchone():
            raise ValueError('durable jobs must observe their existing intent, not migrate legacy state')
    settings=json.loads((b.STATE/'native.json').read_text())
    source=native.task_record(settings,task,route['author'])
    if not eligible(route,source,native.issue_task_runs(settings,issue)):
        raise ValueError('latest terminal native source required')
    for role in ('copy','red'):
        if b.docker('GET','/containers/'+b.PREFIX+'-test-first-'+role+'-'+task+'/json'):
            raise ValueError('legacy job must be independently observed before migration')
    frozen=b.docker('GET','/volumes/'+snap['volume'])
    if any((frozen or {}).get('Labels',{}).get(k)!=v for k,v in
            {'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':task}.items()):
        raise ValueError('owned immutable failed snapshot required')
    # The new fixed copy validates every byte against the frozen snapshot and
    # original base. Existing output is resumed, never erased or overwritten.
    new={**saved,'status':'capturing','timeout_observation_recovery':dict(
        operation='legacy_checkpoint_observation_migration_v1',previous=saved,
        maintenance_operation=barrier['operation_id'],new_job_protocol='test-first-v2',
        author_restarted=False,delivery_approved=False)}
    with b.db() as con:
        current=proof(con,issue,task)
        if current!=saved:raise ValueError('checkpoint changed during migration')
        con.execute('UPDATE failed_test_checkpoint_executions SET receipt=? WHERE source_task=?',
            (json.dumps(new,sort_keys=True),task))
    return new
