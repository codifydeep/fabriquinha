"""Immutable v2 test-review assignment and one-shot native dispatch/admission.

Controller-only source adapter. Dispatch has a separate default-off feature gate:
it must not be enabled before its read-only worker launch is qualified. Neither
assignment, native wakeup nor capability approves tests or authorizes Green.
"""
import hashlib
import json
import secrets
import time
import uuid
from execution_context import freeze, validate as validate_capsule
from quality_phase_tools import validate as validate_phase

try:
    from . import quality_progress as progress, quality_red_capture as capture, quality_author_admission as author
    from . import controller_maintenance as maintenance, maintenance_job_clock as clock, native, validation_job
except ImportError:
    import quality_progress as progress, quality_red_capture as capture, quality_author_admission as author
    import controller_maintenance as maintenance, maintenance_job_clock as clock, native, validation_job

quality = capture.quality
require = capture.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_test_reviews('
        'source_task TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_admissions('
        'source_task TEXT PRIMARY KEY,task_id TEXT UNIQUE,request_id TEXT UNIQUE,context TEXT,context_sha256 TEXT)')


def load(b, source):
    capture.enrollment.canonical(source)
    with b.db() as con:
        initialize(con)
        row = con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_test_reviews '
            'WHERE source_task=?', (source,)).fetchone()
        if not row:
            return None
        context, state = json.loads(row[0]), json.loads(row[1])
        require(quality.digest(context) == row[2] and quality.digest(state) == row[3]
            and context['namespace'] == b.PREFIX and context['source_task'] == source)
        e = capture.enrollment.lookup(con, context['packet']['issue_id'])
        require(e is not None and quality.digest(e) == context['enrollment_sha256'])
        require(state.get('tests_approved') is False and state.get('delivery_approval') is False)
    return context, state


def instruction(packet):
    return ('INDEPENDENT V2 TEST REVIEW. Review the frozen snapshot, existing tests, '
        'new tests, product code and acceptance mapping. Judge meaningful assertions, '
        'coverage and preservation, not just a failing count. Red is already observed; '
        'do not overwrite code or recreate Red. Only registered read_file pages are '
        'allowed, offset>=1 and limit<=100. No terminal, patches, writes, delegation, '
        'administration or claimed execution. Approval is for frozen tests and later '
        'implementation only, never merge/delivery. Request changes with concrete '
        'file/test/criterion findings when inadequate; technical review problems go '
        'to the CTO, not the CEO. Return ONLY JSON with exactly action (approve_tests, request_changes '
        'or escalate_cto), reason (<=1200 characters), manifest_sha256, plan_sha256, red_sha256, '
        'criteria (all registered IDs) and findings. Approval requires findings=[]. Changes require '
        'concrete findings: {criterion,path,test,line,quote,expected,observed}; path is relative, '
        'test is an existing new-test method or __module__, line is 1-based, and quote must appear '
        'on the exact observed line. No extra fields or claimed read/approval booleans.\n'
        'Plan: '+packet['plan_sha256']+'\nRed: '+packet['red_sha256']+
        '\nSnapshot: '+packet['manifest_sha256'])


def prepare(b, source):
    """Prepare only from an authenticated controller capture, never agent input."""
    require(getattr(b, 'QUALITY_V2_ENABLED', False) is True)
    capture.enrollment.canonical(source)
    with capture.observation_lock(b, source):
        previous = load(b, source)
        if previous:
            return previous
        entry = progress.load(b, source)
        require(entry is not None and entry[1]['stage'] == 'review_ready')
        saved = entry[1]
        with b.db() as con:
            row = con.execute('SELECT state FROM quality_red_captures WHERE task_id=?', (source,)).fetchone()
            require(row is not None)
        packet = progress.packet(b, source, json.loads(row[0]))
        require(packet == saved['packet'] and quality.digest(packet) == saved['packet_sha256'])
        e, plan, spec, binding, lead = capture.authorize_source(b, source)
        require(packet['plan'] == plan and plan['author'] != plan['reviewer'])
        with b.db() as con:
            origin = author.load(con, binding['request_id'])
        require(origin is not None and origin['task_id'] == source and origin['agent_id'] == plan['author']
            and origin['plan_sha256'] == quality.digest(plan))
        observed_issue = native.issue_record(json.loads((b.STATE/'native.json').read_text()), e['issue_id'])
        require({key: observed_issue.get(key) for key in ('id','workspace_id','title','description')} == origin['issue'])
        cto = getattr(b, 'QUALITY_CTO', None)
        capture.enrollment.canonical(cto)
        settings = json.loads((b.STATE/'native.json').read_text())
        require(settings['agents'].get(cto) == 'planning')
        context = dict(namespace=b.PREFIX, source_task=source, enrollment_sha256=quality.digest(e),
            packet=packet, packet_sha256=quality.digest(packet),
            read_paths=['/delivery/'+p for p in sorted(spec['files'])],
            reviewer=plan['reviewer'], techlead=lead, cto=cto,
            author_context_sha256=quality.digest(origin), requirements=origin['issue'],
            capsule=freeze(origin['capsule']['description'], instruction(packet)),
            instruction=instruction(packet))
        context['marker'] = quality.digest(context)
        validate_phase(dict(version=2, phase='test_review_v2', request_id=source,
            editable_paths=[], read_paths=context['read_paths']), source)
        state = dict(stage='prepared', owner=plan['reviewer'], tests_approved=False,
            execution_authorized=False, delivery_approval=False)
        with b.LOCK, b.db() as con:
            maintenance.transaction(con)
            require(not maintenance.current(con) and capture.source(con, source) == binding
                and capture.enrollment.lookup(con, e['issue_id']) == e)
            con.execute('INSERT INTO quality_test_reviews VALUES(?,?,?,?,?)',
                (source, json.dumps(context, sort_keys=True), json.dumps(state, sort_keys=True),
                 quality.digest(context), quality.digest(state)))
        return context, state


def save(b, source, context, before, after):
    with b.LOCK, b.db() as con:
        maintenance.transaction(con)
        require(not maintenance.current(con))
        changed = con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=? '
            'WHERE source_task=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after, sort_keys=True), quality.digest(after), source,
             quality.digest(context), quality.digest(before)))
        require(changed.rowcount == 1)
    return after


def dispatch(b, source):
    require(getattr(b, 'QUALITY_REVIEW_ENABLED', False) is True)
    context, _ = prepare(b, source)
    with capture.observation_lock(b, source):
        context, state = load(b, source)
        if state['stage'] in ('awaiting_review', 'admitted', 'technical_blocked'):
            return state
        require(state['stage'] in ('prepared', 'dispatch_intent'))
        with b.db() as con:
            require(not maintenance.current(con))
        settings = json.loads((b.STATE/'native.json').read_text())
        with b.db() as con:
            e = capture.enrollment.lookup(con, context['packet']['issue_id'])
        require(settings['workspace_id'] == e['workspace_id'] and settings['runtime_id'] == e['runtime_id']
            and settings['agents'].get(context['reviewer']) == 'review')
        allow_create = state['stage'] == 'prepared'
        if allow_create:
            state = save(b, source, context, state,
                {**state, 'stage': 'dispatch_intent', 'deadline': time.time()+600})
        with b.db() as con:
            deadline = clock.deadline(con, b.PREFIX, state['deadline'], time.time())
        # Persist first. A crash before/after POST must only GET the same marker.
        # No observed wakeup means uncertainty, not permission for another POST.
        try:
            wakeup = native.ensure_review_start(settings, context['packet']['issue_id'], context['reviewer'],
                source, context['marker'], context['instruction'], allow_create=allow_create)
            if wakeup is not None:
                capture.enrollment.canonical(wakeup['id'])
                require(wakeup.get('issue_id') == context['packet']['issue_id']
                    and wakeup.get('agent_id') == context['reviewer'])
        except (TimeoutError, OSError):
            wakeup = None
        except (ValueError, KeyError, TypeError):
            return save(b, source, context, state, {**state, 'stage': 'technical_blocked',
                'owner': context['cto'], 'incident': dict(category='review_wakeup_identity_rejected',
                    automatic_retry=False, next_action='CTO inspect preserved wakeup identity; no repeated POST')})
        if wakeup is None:
            if time.time() >= deadline:
                return save(b, source, context, state, {**state, 'stage': 'technical_blocked',
                    'owner': context['cto'], 'incident': dict(category='review_dispatch_unobserved',
                        automatic_retry=False, next_action='CTO diagnose original wakeup intent; no repeated POST')})
            raise validation_job.Pending('review dispatch outcome unknown; preserve original intent')
        return save(b, source, context, state, {**state, 'stage': 'awaiting_review', 'wakeup_id': wakeup['id']})


def admission(con, request):
    initialize(con)
    row = con.execute('SELECT context,context_sha256 FROM quality_review_admissions '
        'WHERE request_id=?', (request,)).fetchone()
    if not row:
        return None
    context = json.loads(row[0])
    require(quality.digest(context) == row[1] and context['request_id'] == request
        and context['phase'] == 'test_review_v2' and context['mode'] == 'review')
    validate_capsule(context['capsule'])
    rows = con.execute('SELECT n.task_id,n.agent_id,n.scope,n.issue_id,g.mode,g.attempt,'
        'q.run_id,q.phase,q.plan_sha256 FROM native_bindings n JOIN grants g USING(request_id) '
        'JOIN quality_native_scopes q ON q.request_id=n.request_id AND q.task_id=n.task_id '
        'WHERE n.request_id=?', (request,)).fetchall()
    require(len(rows) == 1 and tuple(rows[0]) == tuple(context[k] for k in
        ('task_id','agent_id','scope','issue_id','mode','attempt','run_id','phase','plan_sha256')))
    require(con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',
        (context['task_id'],)).fetchone()[0] == 1)
    assignment = con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_test_reviews '
        'WHERE source_task=?', (context['source_task'],)).fetchone()
    require(assignment is not None)
    registered, state = json.loads(assignment[0]), json.loads(assignment[1])
    require(quality.digest(registered) == assignment[2] == context['assignment_sha256']
        and quality.digest(state) == assignment[3] and state['stage'] == 'admitted'
        and state['request_id'] == request and state['review_task'] == context['task_id'])
    return context


def admit(b, source, task_id, agent_id, *, now=None):
    """Mint once for the exact running recipient, not a marker-only claimant."""
    require(getattr(b, 'QUALITY_V2_ENABLED', False) is True
        and getattr(b, 'QUALITY_REVIEW_ENABLED', False) is True)
    for value in (source, task_id, agent_id):
        capture.enrollment.canonical(value)
    context, state = load(b, source)
    require(state['stage'] == 'awaiting_review' and agent_id == context['reviewer']
        and agent_id != context['packet']['author'] and source != task_id)
    e, plan, _, binding, _ = capture.authorize_source(b, source)
    settings = json.loads((b.STATE/'native.json').read_text())
    require(settings['agents'].get(agent_id) == 'review')
    with b.db() as con:
        origin = author.load(con, binding['request_id'])
    require(origin is not None and quality.digest(origin) == context['author_context_sha256'])
    observed_issue = native.issue_record(settings, e['issue_id'])
    require({key: observed_issue.get(key) for key in ('id','workspace_id','title','description')} == context['requirements'])
    task = native.task_record(settings, task_id, agent_id)
    note = 'DELIVERY_REVIEW_START '+context['marker']+'\nSource: '+source+'\n'+context['instruction']
    require(task.get('id') == task_id and task.get('agent_id') == agent_id and task.get('status') == 'running'
        and task.get('issue_id') == e['issue_id'] and task.get('wakeup_id') == state['wakeup_id']
        and task.get('workspace_id') == e['workspace_id'] and task.get('runtime_id') == e['runtime_id']
        and task.get('handoff_note') == note)
    runs = [r for r in native.issue_task_runs(settings, e['issue_id']) if r.get('agent_id') == agent_id]
    require(len(runs) == 1 and runs[0].get('id') == task_id)
    capsule = validate_capsule(context['capsule'])
    now = time.time() if now is None else now
    with b.LOCK, b.db() as con:
        maintenance.require_admission(con)
        recorded = con.execute('SELECT context_sha256,state_sha256 FROM quality_test_reviews '
            'WHERE source_task=?', (source,)).fetchone()
        require(recorded is not None and tuple(recorded) == (quality.digest(context), quality.digest(state))
            and capture.source(con, source) == binding
            and capture.enrollment.lookup(con, e['issue_id']) == e
            and json.loads((b.STATE/'native.json').read_text()) == settings)
        require(not con.execute('SELECT 1 FROM quality_review_admissions WHERE source_task=? OR task_id=?',
            (source, task_id)).fetchone())
        require(not con.execute('SELECT 1 FROM native_bindings WHERE task_id=?', (task_id,)).fetchone())
        require(not con.execute('SELECT 1 FROM grants WHERE task_id=?', (task_id,)).fetchone())
        require(not con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) '
            'WHERE g.used=1 AND l.request_id IS NULL LIMIT 1').fetchone())
        active = con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
        reserved = con.execute('SELECT count(*) FROM grants WHERE used=0 AND deadline>?', (now,)).fetchone()[0]
        require(active+reserved < 2)
        require(not con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
            "WHERE n.agent_id=? AND l.status IN ('creating','starting','running','closing')", (agent_id,)).fetchone())
        require(not con.execute('SELECT 1 FROM native_bindings n JOIN grants g USING(request_id) '
            'WHERE n.agent_id=? AND g.used=0 AND g.deadline>?', (agent_id, now)).fetchone())
        request = str(uuid.uuid4())
        token = secrets.token_hex(32)
        admitted = dict(namespace=b.PREFIX, source_task=source, issue_id=e['issue_id'], task_id=task_id,
            agent_id=agent_id, scope=e['workspace_id']+':'+agent_id+':review:'+task_id,
            request_id=request, mode='review', attempt=1, phase='test_review_v2', run_id=e['run_id'],
            plan_sha256=e['plan_sha256'], assignment_sha256=quality.digest(context),
            packet_sha256=context['packet_sha256'], snapshot_volume=context['packet']['snapshot_volume'],
            manifest_sha256=context['packet']['manifest_sha256'], capsule=capsule,
            read_paths=context['read_paths'])
        con.execute('INSERT INTO grants(digest,task_id,attempt,mode,request_id,deadline,used) VALUES(?,?,?,?,?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(), task_id, 1, 'review', request, now+480, 0))
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
            (request, task_id, agent_id, admitted['scope'], e['issue_id']))
        con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
            (request, task_id, e['run_id'], 'test_review_v2', e['plan_sha256']))
        con.execute('INSERT INTO quality_review_admissions VALUES(?,?,?,?,?)',
            (source, task_id, request, json.dumps(admitted, sort_keys=True), quality.digest(admitted)))
        after = {**state, 'stage': 'admitted', 'review_task': task_id, 'request_id': request}
        con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=? WHERE source_task=?',
            (json.dumps(after, sort_keys=True), quality.digest(after), source))
    return dict(capability=token, request_id=request, task_id=task_id, attempt=1, mode='review')


def tool_config(b, request):
    require(getattr(b, 'QUALITY_V2_ENABLED', False) is True
        and getattr(b, 'QUALITY_REVIEW_ENABLED', False) is True)
    with b.db() as con:
        c = admission(con, request)
        require(c is not None and c['namespace'] == b.PREFIX)
    context, state = load(b, c['source_task'])
    require(quality.digest(context) == c['assignment_sha256'] and state['stage'] == 'admitted'
        and state['request_id'] == request and state['review_task'] == c['task_id'])
    return dict(version=2, phase='test_review_v2', request_id=request,
        editable_paths=[], read_paths=c['read_paths'])
