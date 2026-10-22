"""Controller-only fair v2 snapshot/Red reconciliation, not review authority.

Discover sources from consumed, closed native phase bindings. Each invocation
observes the original durable snapshot/validation jobs; it never creates another
author capability. Review-ready packets retain exact evidence for the forthcoming
review admission adapter. No worker endpoint, native wakeup or approval is added.
"""
import fcntl
import json
import os
import stat
import time
from contextlib import contextmanager

try:
    from . import controller_maintenance as maintenance
    from . import quality_red_capture as capture, quality_red_snapshot as snapshot
    from . import validation_job
except ImportError:
    import controller_maintenance as maintenance
    import quality_red_capture as capture, quality_red_snapshot as snapshot
    import validation_job

quality = capture.quality
require = capture.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_progress('
        'task_id TEXT PRIMARY KEY,identity TEXT,state TEXT,identity_sha256 TEXT,'
        'state_sha256 TEXT,observed_at REAL)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_progress_discovery('
        'task_id TEXT PRIMARY KEY,state TEXT,state_sha256 TEXT,observed_at REAL)')


@contextmanager
def exclusive(b):
    """A process crash releases the lock; no timestamp-based lock stealing."""
    fd = os.open(b.STATE/'quality-progress.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid())
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise validation_job.Pending('original quality reconciliation is still active') from None
        yield
    finally:
        os.close(fd)


def candidates(b):
    with b.db() as con:
        initialize(con)
        if not capture.enrollment.exists(con, 'quality_native_scopes'):
            return []
        rows = con.execute("SELECT DISTINCT q.task_id FROM quality_native_scopes q "
            "JOIN native_bindings n USING(request_id,task_id) "
            "JOIN grants g USING(request_id) JOIN leases l USING(request_id) "
            "WHERE q.phase='tests_only_v2' AND g.used=1 AND l.status='closed'").fetchall()
        selected = []
        for row in rows:
            task = row[0]
            discovery = con.execute('SELECT state,state_sha256,observed_at FROM quality_progress_discovery '
                'WHERE task_id=?', (task,)).fetchone()
            if discovery:
                finding = json.loads(discovery[0])
                require(quality.digest(finding) == discovery[1])
                if finding['stage'] == 'authority_blocked':
                    continue
            prior = con.execute('SELECT state,state_sha256,observed_at FROM quality_progress '
                'WHERE task_id=?', (task,)).fetchone()
            if prior:
                state = json.loads(prior[0])
                require(quality.digest(state) == prior[1])
                if state['stage'] in ('review_ready', 'technical_blocked'):
                    continue
            selected.append((max(prior[2] if prior else 0, discovery[2] if discovery else 0), task))
        return [task for _, task in sorted(selected)]


def load(b, task):
    with b.db() as con:
        initialize(con)
        row = con.execute('SELECT identity,state,identity_sha256,state_sha256 FROM quality_progress '
            'WHERE task_id=?', (task,)).fetchone()
        if not row:
            return None
        identity, state = json.loads(row[0]), json.loads(row[1])
        require(quality.digest(identity) == row[2] and quality.digest(state) == row[3])
        require(identity['namespace'] == b.PREFIX and identity['task_id'] == task)
        return identity, state


def save(b, task, identity, before, after):
    with b.LOCK, b.db() as con:
        maintenance.transaction(con)
        require(not maintenance.current(con))
        changed = con.execute('UPDATE quality_progress SET state=?,state_sha256=?,observed_at=? '
            'WHERE task_id=? AND identity_sha256=? AND state_sha256=?',
            (json.dumps(after, sort_keys=True), quality.digest(after), time.time(), task,
             quality.digest(identity), quality.digest(before)))
        require(changed.rowcount == 1)
    return after


def packet(b, task, result):
    """Read only controller capture rows, not a returned agent report."""
    with b.db() as con:
        row = con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_red_captures '
            'WHERE task_id=?', (task,)).fetchone()
        require(row is not None)
        context, state = json.loads(row[0]), json.loads(row[1])
        require(quality.digest(context) == row[2] and quality.digest(state) == row[3] and state == result)
        e = capture.enrollment.lookup(con, context['plan']['issue_id'])
        require(e is not None and e['namespace'] == b.PREFIX
            and quality.digest(e) == context['enrollment_sha256'])
    plan = context['plan']
    quality.validate(plan)
    quality.red(plan, state['red'])
    require(state['stage'] == 'awaiting_independent_test_review' and state['owner'] == plan['reviewer']
        and state['execution_authorized'] is False and state['delivery_approval'] is False
        and state['red']['task_id'] == task
        and state['red']['manifest_sha256'] == context['copy']['prepared']['manifest_sha256'])
    return dict(operation='quality_test_review_packet_v2', task_id=task,
        run_id=plan['run_id'], issue_id=plan['issue_id'], author=plan['author'], reviewer=plan['reviewer'],
        plan=plan, plan_sha256=quality.digest(plan), red=state['red'], red_sha256=quality.digest(state['red']),
        capture_context_sha256=row[2], capture_state_sha256=row[3],
        manifest_sha256=state['red']['manifest_sha256'], snapshot_volume=b.PREFIX+'-quality-red-'+task,
        frozen_test_candidates=state['red']['tests'], execution_authorized=False,
        tests_approved=False, delivery_approval=False)


def advance(b, task):
    capture.enrollment.canonical(task)
    previous = load(b, task)
    if previous and previous[1]['stage'] in ('review_ready', 'technical_blocked'):
        return previous[1]
    if not previous:
        # Native completion can lag the broker lease close. Observe that same
        # task; a still-running native record is not a failed Red or new attempt.
        with b.db() as con:
            binding = capture.source(con, task)
            enrolled = capture.enrollment.lookup(con, binding['issue_id'])
            require(enrolled is not None and enrolled['namespace'] == b.PREFIX)
        settings = json.loads((b.STATE/'native.json').read_text())
        require(settings['workspace_id'] == enrolled['workspace_id']
            and settings['runtime_id'] == enrolled['runtime_id']
            and settings['agents'].get(binding['agent_id']) == 'implementation')
        current = capture.native.task_record(settings, task, binding['agent_id'])
        require(current.get('id') == task and current.get('agent_id') == binding['agent_id']
            and current.get('issue_id') == binding['issue_id'])
        if current.get('status') in ('pending', 'queued', 'running'):
            return dict(stage='waiting_native_completion', owner=binding['agent_id'],
                execution_authorized=False, delivery_approval=False)
        e, plan, _, binding, lead = capture.authorize_source(b, task)
        identity = dict(namespace=b.PREFIX, task_id=task, source=binding,
            enrollment_sha256=quality.digest(e), plan_sha256=quality.digest(plan), techlead=lead)
        state = dict(stage='observing', owner=plan['author'], error_count=0,
            execution_authorized=False, delivery_approval=False)
        with b.LOCK, b.db() as con:
            maintenance.transaction(con)
            require(not maintenance.current(con) and capture.source(con, task) == binding)
            require(quality.digest(capture.enrollment.lookup(con, e['issue_id'])) == identity['enrollment_sha256'])
            con.execute('INSERT INTO quality_progress VALUES(?,?,?,?,?,?)',
                (task, json.dumps(identity, sort_keys=True), json.dumps(state, sort_keys=True),
                 quality.digest(identity), quality.digest(state), time.time()))
    else:
        identity, state = previous
    try:
        result = snapshot.advance(b, task)
        if result['stage'] == 'awaiting_independent_test_review':
            review = packet(b, task, result)
            after = dict(stage='review_ready', owner=review['reviewer'], packet=review,
                packet_sha256=quality.digest(review), next_action='admit independent read-only test review',
                execution_authorized=False, delivery_approval=False)
        else:
            require(result['stage'] == 'technical_blocked')
            after = dict(stage='technical_blocked', owner=identity['techlead'],
                incident=dict(category='snapshot_or_red_blocked', evidence_sha256=quality.digest(result),
                    automatic_retry=False, next_action='Tech Lead inspect preserved snapshot/Red incident'),
                execution_authorized=False, delivery_approval=False)
    except validation_job.Pending:
        # Observation of the same durable job, never a fresh execution attempt.
        after = {**state, 'stage': 'observing', 'next_action': 'observe original immutable snapshot/Red job'}
    except (TimeoutError, OSError) as error:
        category = type(error).__name__
        count = state.get('error_count', 0) + 1 if state.get('error_category') == category else 1
        after = {**state, 'error_category': category, 'error_count': count,
            'next_action': 'observe original immutable job; no new author grant'}
        if count >= 2:
            after.update(stage='technical_blocked', owner=identity['techlead'],
                incident=dict(category='repeated_observation_failure', automatic_retry=False,
                    next_action='Tech Lead diagnose preserved job before changed-condition recovery'))
    except (ValueError, KeyError, TypeError):
        after = dict(stage='technical_blocked', owner=identity['techlead'],
            incident=dict(category='quality_progress_provenance_rejected', automatic_retry=False,
                next_action='Tech Lead inspect authenticated source/capture; no identical retry'),
            execution_authorized=False, delivery_approval=False)
    return save(b, task, identity, state, after)


def observation(b, task, result):
    """Fairness cursor and bounded discovery failures survive process restarts."""
    with b.LOCK, b.db() as con:
        maintenance.transaction(con)
        require(not maintenance.current(con))
        previous = con.execute('SELECT state,state_sha256 FROM quality_progress_discovery '
            'WHERE task_id=?', (task,)).fetchone()
        old = json.loads(previous[0]) if previous else {}
        if previous:
            require(quality.digest(old) == previous[1])
        state = dict(result)
        if result['stage'] == 'authority_rejected':
            count = old.get('error_count', 0) + 1 if old.get('stage') == 'authority_rejected' else 1
            state.update(error_count=count, owner=getattr(b, 'QUALITY_TECHLEAD', None))
            if count >= 2:
                state.update(stage='authority_blocked', automatic_retry=False,
                    next_action='Tech Lead inspect discovery authority; changed-condition recovery required')
        con.execute('INSERT INTO quality_progress_discovery VALUES(?,?,?,?) '
            'ON CONFLICT(task_id) DO UPDATE SET state=excluded.state,state_sha256=excluded.state_sha256,'
            'observed_at=excluded.observed_at',
            (task, json.dumps(state, sort_keys=True), quality.digest(state), time.time()))
    return state


def tick(b, *, limit=2):
    """Opt-in coordinator hook; legacy controller schedules do not invoke it."""
    require(type(limit) is int and 1 <= limit <= 2)
    if getattr(b, 'QUALITY_V2_ENABLED', False) is not True:
        return dict(stage='disabled', observed=[], delivery_approval=False)
    with exclusive(b):
        with b.db() as con:
            if maintenance.current(con):
                return dict(stage='maintenance', observed=[], delivery_approval=False)
        observed = []
        for task in candidates(b)[:limit]:
            try:
                state = advance(b, task)
                result = dict(task_id=task, stage=state['stage'], owner=state['owner'])
            except (TimeoutError, OSError):
                result = dict(task_id=task, stage='authority_rejected', category='observation_unavailable')
            except (ValueError, KeyError, TypeError) as error:
                # A corrupt/unadmitted row is visible, but cannot starve another
                # source or be interpreted as a successful handoff.
                result = dict(task_id=task, stage='authority_rejected', category=type(error).__name__)
            observed.append(observation(b, task, result))
        return dict(stage='observed', observed=observed, delivery_approval=False)
