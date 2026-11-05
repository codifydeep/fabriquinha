"""Durable, ordered negative-control submissions. Only the live native author claim can hand off."""
import json

from .artifacts import digest
from .board import Run
from .effects import write_json, EffectBlocked
from .quality import Quality


class NextControl(Exception):
    """A bounded worker completed its local validation step."""


def seal(quality, origin, green_key, mutants, *, legacy=False):
    green = quality.store.receipt(green_key, kind='green')
    data = green['payload']
    if (green['binding'] != origin.binding() or origin.kind != 'implementation'
            or origin.reviewing or origin.actor != origin.author
            or data['project'] != quality.project.fingerprint()
            or not 1 <= len(mutants) <= 8 or len(set(mutants)) != len(mutants)):
        raise ValueError('exact author Green and distinct ordered mutations required')
    for mutant in mutants:
        if mutant == data['snapshot']:
            raise ValueError('control must change product')
        quality.protect(data['snapshot'], mutant, exact_tests=True)
    return quality.store.record('control_submission', origin.binding(), dict(
        green=green_key, snapshot=data['snapshot'], freeze=data['freeze'], mutants=list(mutants),
        project=data['project'], legacy=legacy, delivery_approval=False))


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
        controls = fixed.controls(origin, data['green'], data['mutants'])
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


def previous_submission(conn, store, run):
    row = conn.execute('SELECT id,outcome,summary FROM task_runs WHERE task_id=? AND id<? ORDER BY id DESC LIMIT 1',
                       (run.task, run.number)).fetchone()
    if not row:
        return None
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
        if row['outcome']=='blocked' and record['kind']!='legacy_control_claim':
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
