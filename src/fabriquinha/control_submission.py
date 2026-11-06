"""Durable, ordered negative-control submissions. Only the live native author claim can hand off."""
import json

from .artifacts import digest
from .board import Run
from .effects import write_json, EffectBlocked
from .quality import Quality, MAX_CONTROL_MUTATIONS, validate_control_targets


class NextControl(Exception):
    """A bounded worker completed its local validation step."""


def seal(quality, origin, green_key, mutants, *, legacy=False, targets=None):
    green = quality.store.receipt(green_key, kind='green')
    data = green['payload']
    if (green['binding'] != origin.binding() or origin.kind != 'implementation'
            or origin.reviewing or origin.actor != origin.author
            or data['project'] != quality.project.fingerprint()
            or not 1 <= len(mutants) <= MAX_CONTROL_MUTATIONS or len(set(mutants)) != len(mutants)):
        raise ValueError('exact author Green and distinct ordered mutations required')
    if targets is not None:
        validate_control_targets(quality.freeze(origin, data['freeze'])['control_cases'], len(mutants), targets)
    for mutant in mutants:
        if mutant == data['snapshot']:
            raise ValueError('control must change product')
        quality.protect(data['snapshot'], mutant, exact_tests=True)
    return quality.store.record('control_submission', origin.binding(), dict(
        green=green_key, snapshot=data['snapshot'], freeze=data['freeze'], mutants=list(mutants),
        project=data['project'], legacy=legacy, delivery_approval=False, **({'targets': targets} if targets is not None else {})))


class OneControl:
    def __init__(self, store, delegate, plan, submission):
        self.store, self.delegate = store, delegate
        self.plan, self.submission = plan, submission
        self.executed = False
        self.job_scope = None if plan['payload']['legacy'] else submission
        self.delegate.control_submission = self.job_scope

    def run(self, origin, snapshot, phase):
        if (phase != 'control' or origin.binding() != self.plan['binding']
                or snapshot not in self.plan['payload']['mutants']):
            raise ValueError('job outside sealed control submission')
        folder = self.store.root/'control-submissions'/self.submission
        index = self.plan['payload']['mutants'].index(snapshot)
        path = folder/(str(index)+'.json')
        if path.exists():
            checkpoint = json.loads(path.read_bytes())
            if checkpoint != dict(submission=self.submission, mutant=snapshot, job=checkpoint.get('job')):
                raise ValueError('control checkpoint identity changed')
            # Quality.observe revalidates the job binding, image, preview and report.
            receipt = self.store.receipt(checkpoint['job'], kind='suite_job')
            if receipt['payload']['identity'].get('control_submission') != self.job_scope:
                raise ValueError('control job belongs to another submission')
            return checkpoint['job']
        if self.executed:
            raise NextControl()
        self.executed = True
        job = self.delegate.run(origin, snapshot, phase)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json(path, dict(submission=self.submission, mutant=snapshot, job=job))
        return job


class BoundEvidence:
    """Restrict historical evidence reads to one submission under a current native claim."""
    def __init__(self, board, live, plan):
        self.board, self.live, self.plan = board, live, plan

    def ensure(self, origin):
        self.board.ensure(self.live)
        if (origin.binding() != self.plan['binding'] or not self.live.same_subject(origin.binding())
                or self.live.number < origin.number):
            raise ValueError('foreign control continuation')

    def input(self, origin, key):
        self.ensure(origin)
        if key != 'tests' or self.board.input(self.live, key) != self.plan['payload']['freeze']:
            raise ValueError('control continuation freeze changed')
        return self.plan['payload']['freeze']


def advance(quality, live, submission):
    store = quality.store
    plan = store.receipt(submission, kind='control_submission')
    origin = Run(**plan['binding'])
    data = plan['payload']
    guard = BoundEvidence(quality.board, live, plan)
    guard.input(origin, 'tests')
    green = store.receipt(data['green'], kind='green')
    if (green['binding'] != origin.binding() or green['payload']['snapshot'] != data['snapshot']
            or green['payload']['freeze'] != data['freeze'] or data['project'] != quality.project.fingerprint()
            or store.capture(quality.board.workspace(live)) != data['snapshot']):
        raise EffectBlocked('changed Green, workspace or freeze; preserve submission')
    fixed = Quality(quality.project, store, OneControl(store, quality.runner, plan, submission), guard)
    try:
        controls = fixed.controls(origin, data['green'], data['mutants'], collect_survivors=True)
    finally:
        quality.control_refusal = fixed.control_refusal
        quality.suite_refusal = fixed.suite_refusal
    frozen = fixed.freeze(origin, data['freeze'])
    evidence = dict(green=data['green'], controls=controls)
    guard.ensure(origin)
    quality.board.review(live, 'Complete controller-validated negative controls', evidence,
                         exclude=(frozen['test_author'],))
    return dict(status='review_requested', task=live.task, evidence=evidence, delivery_approval=False)


def wait_payload(store, project, run, submission):
    plan = store.receipt(submission, kind='control_submission')
    if (not run.same_subject(plan['binding']) or plan['binding']['number'] > run.number
            or plan['payload']['project'] != project.fingerprint()):
        raise ValueError('foreign control wait')
    return store.record('control_wait', run.binding(), dict(submission=submission,
                        project=project.fingerprint(), delivery_approval=False))


def unfinished_survivor(store, row, claim):
    """A known fail-fast veto may resume observation of its outstanding suffix."""
    try:
        detail = json.loads(row['summary'] or '{}')
        failure = store.receipt(detail['failure'], kind='worker_failure')
    except (KeyError, ValueError, TypeError):
        return False
    prefix = 'negative control must fail the complete frozen suite: '
    message = failure['payload'].get('message','')
    if failure['binding'] != claim['binding'] or not message.startswith(prefix):
        return False
    result = json.loads(message[len(prefix):])
    key = claim['payload']['submission']
    plan = store.receipt(key, kind='control_submission')
    index = result['index']
    if type(index) is not int or not 1 <= index < len(plan['payload']['mutants']):
        return False
    mutant = plan['payload']['mutants'][index-1]
    path = store.root/'control-submissions'/key/(str(index-1)+'.json')
    return (result['failures']==0 and result['membership_matches'] is True
            and result['snapshot']==mutant and path.is_file()
            and json.loads(path.read_bytes())==dict(submission=key,mutant=mutant,job=result['job']))


def previous_submission(conn, store, run):
    before = run.number
    while True:
        row = conn.execute('SELECT id,outcome,summary,error,worker_pid,worker_started_at,ended_at FROM task_runs '
                           'WHERE task_id=? AND id<? ORDER BY id DESC LIMIT 1', (run.task,before)).fetchone()
        if row is None:
            return None
        if row['outcome'] != 'spawn_failed':
            break
        reason = 'operational pause; no worker started'
        if (row['error'] != reason or row['worker_pid'] is not None or row['worker_started_at'] is not None
                or not row['ended_at']):
            return None
        event = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='spawn_failed' "
                             "ORDER BY id DESC LIMIT 1", (run.task,row['id'])).fetchone()
        observed = json.loads(event['payload']) if event else {}
        if observed.get('error') != reason or observed.get('infrastructure') is not True or observed.get('retry_status') != 'ready':
            return None
        before = row['id']
    if row['outcome'] == 'scheduled':
        event = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='scheduled' ORDER BY id DESC LIMIT 1",
                             (run.task, row['id'])).fetchone()
        if event:
            try:
                reason = json.loads(json.loads(event['payload'])['reason'])
            except (TypeError, ValueError, KeyError):
                return None
            if isinstance(reason, dict) and set(reason) == {'control_wait'}:
                record = store.receipt(reason['control_wait'], kind='control_wait')
                if record['binding'] != {**run.binding(), 'number':row['id']}:
                    raise ValueError('control wait belongs to another claim')
                return record['payload']['submission']
    # A controller checkpoint also survives death between two native transitions.
    path = store.root/'control-claims'/(digest([run.task,row['id']])+'.json')
    if row['outcome'] in ('timed_out','failed','blocked') and path.exists():
        record = store.receipt(json.loads(path.read_bytes())['claim'])
        if record['kind'] not in ('control_claim','legacy_control_claim'):
            raise ValueError('invalid continuation claim')
        if (row['outcome']=='blocked' and record['kind']!='legacy_control_claim'
                and not unfinished_survivor(store,row,record)):
            return None  # A rejected submission goes through native technical recovery.
        if record['binding'] != {**run.binding(), 'number':row['id']}:
            raise ValueError('stale continuation claim')
        return record['payload']['submission']
    return None


def bind_claim(store, run, submission, *, legacy=False):
    record = store.receipt(submission, kind='control_submission')
    if not run.same_subject(record['binding']) or record['binding']['number'] > run.number:
        raise ValueError('cannot transfer control plan between subjects')
    path = store.root/'control-claims'/(digest([run.task,run.number])+'.json')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    claim = store.record('legacy_control_claim' if legacy else 'control_claim',run.binding(),dict(submission=submission))
    if path.exists() and json.loads(path.read_bytes()) != {'claim':claim}:
        raise ValueError('control claim already bound to another submission')
    write_json(path,dict(claim=claim))


def refusal_origin(store, project, live_binding, record):
    """Resolve diagnostic provenance only through the exact persisted native claim."""
    if live_binding == record['binding']:
        return live_binding
    live = Run(**live_binding)
    path = store.root/'control-claims'/(digest([live.task,live.number])+'.json')
    if not path.is_file() or not live.same_subject(record['binding']) or live.number <= record['binding']['number']:
        raise ValueError('refusal lacks an exact continuation claim')
    claim = store.receipt(json.loads(path.read_bytes())['claim'], kind='control_claim')
    submission = claim['payload']['submission']
    plan = store.receipt(submission, kind='control_submission')
    data = plan['payload']
    if claim['binding'] != live_binding or plan['binding'] != record['binding'] or data['project'] != project.fingerprint():
        raise ValueError('refusal origin differs from sealed plan')
    def check_job(job, mutant):
        identity = job['payload']['identity']
        if (job['binding'] != plan['binding'] or identity['binding'] != plan['binding']
                or identity['phase'] != 'control' or identity['snapshot'] != mutant
                or identity['project'] != data['project'] or identity['image'] != project.validation_image
                or identity.get('control_submission') != (None if data['legacy'] else submission)):
            raise ValueError('refusal job differs from sealed plan')
    if record['kind']=='control_refusal':
        refusal = record['payload']
        if (refusal['green'] != data['green'] or len(refusal['jobs']) != len(data['mutants'])
                or refusal['snapshot'] != data['snapshot'] or refusal['freeze'] != data['freeze']):
            raise ValueError('refusal belongs to another control submission')
        for key, mutant in zip(refusal['jobs'],data['mutants']):
            check_job(store.receipt(key,kind='suite_job'),mutant)
    elif record['kind']=='suite_job':
        mutant = record['payload']['identity']['snapshot']
        if mutant not in data['mutants']:
            raise ValueError('refused job outside submission')
        check_job(record,mutant)
    else:
        raise ValueError('unsupported continuation refusal')
    return plan['binding']


def retained_edit(original, mutant):
    """Return a bounded unique line edit that recreates this exact disposable mutant."""
    left, right = original.splitlines(True), mutant.splitlines(True)
    start = 0
    while start < min(len(left), len(right)) and left[start] == right[start]:
        start += 1
    end, stop = len(left), len(right)
    while end > start and stop > start and left[end-1] == right[stop-1]:
        end -= 1
        stop -= 1
    while True:
        before, after = ''.join(left[start:end]), ''.join(right[start:stop])
        if len(before) + len(after) > 4096:
            return None
        if before and original.count(before) == 1 and original.replace(before, after, 1) == mutant:
            return dict(before=before, after=after)
        if start:
            start -= 1
        elif end < len(left):
            end += 1
            stop += 1
        else:
            return None


def mutation_guidance(store, project, incident):
    """Return prior edits as authoring material. Every resubmission executes new jobs."""
    from .recovery import control_refusal_context
    facts = incident['payload']
    key = facts['control_refusal']
    refusal = store.receipt(key, kind='control_refusal')['payload']
    control_refusal_context(store, project, incident['binding'], key, facts['snapshot'])
    jobs = refusal.get('jobs', [])  # Historical summaries have no replayable mutations.
    records = [store.receipt(job, kind='suite_job')['payload'] for job in jobs]
    submission = records[0]['identity'].get('control_submission') if records else None
    if not submission:
        return None
    plan = store.receipt(submission, kind='control_submission')['payload']
    if (plan['green'] != refusal['green'] or plan['freeze'] != refusal['freeze']
            or plan['snapshot'] != facts['snapshot'] or len(records) != len(plan['mutants'])
            or 'targets' not in plan):
        return None
    base = store.tree(plan['snapshot'])
    manifest = store.manifest(plan['snapshot'])
    items = []
    edit_budget = 24000
    for i, job in enumerate(records):
        mutant = plan['mutants'][i]
        if job['identity'].get('control_submission') != submission or job['identity']['snapshot'] != mutant:
            raise ValueError('control guidance requires the exact ordered jobs')
        tree = store.tree(mutant)
        changed = {p for p, meta in store.manifest(mutant).items() if manifest.get(p) != meta}
        edits = {p: retained_edit((base/p).read_text(), (tree/p).read_text()) for p in sorted(changed)}
        cost = len(json.dumps(edits))
        if not all(edits.values()) or cost > edit_budget:
            edits = None
        else:
            edit_budget -= cost
        failures = job['report']['failures']
        items.append(dict(index=i+1, targets=plan['targets'][i], survived=not failures,
                          observed=sorted({f['case'] for f in failures if f['assertion']})[:32],
                          edits=edits))
    return dict(submission=submission, green=plan['green'], freeze=plan['freeze'], controls=items,
                instruction='Retain effective exact edits on the same source. Diagnose each survivor against its '
                'intended behavior. If legal play differs and the test cannot distinguish it, escalate the '
                'reachable scenario for independent test review. All new submissions require fresh executions.')


def prior_batch_for_retry(conn, store, project, context):
    """Look up the last completed rejection on the same native author and frozen source."""
    rows = conn.execute("SELECT id,summary FROM task_runs WHERE task_id=? AND id<? AND outcome='blocked' "
                        "ORDER BY id DESC LIMIT 16", (context['source'], context['source_run']))
    for number, summary in rows:
        try:
            key = json.loads(summary or '{}')['failure']
        except (ValueError, TypeError, KeyError):
            continue
        failure = store.receipt(key, kind='worker_failure')
        bound = failure['binding']
        if bound['task'] != context['source'] or bound['number'] != number or failure['payload']['project'] != project.fingerprint():
            raise ValueError('historical failure differs from native retry source')
        refusal_key = failure['payload'].get('control_refusal')
        if not refusal_key:
            continue
        refusal = store.receipt(refusal_key, kind='control_refusal')['payload']
        if refusal['freeze'] == context['tests'] and refusal['snapshot'] == context['snapshot']:
            guidance = mutation_guidance(store, project, dict(binding=bound,
                payload=dict(control_refusal=refusal_key, snapshot=context['snapshot'])))
            if guidance:
                return guidance
    return None
