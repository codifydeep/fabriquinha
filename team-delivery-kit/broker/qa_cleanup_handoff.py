"""Bounded native technical escalation, not execution/merge/TDD authority."""
import json
import time
try:
    import qa_cleanup_observer as observer
except ImportError:
    from broker import qa_cleanup_observer as observer

TECHLEAD = '6ff42007-5228-43df-8b95-2a878cfac3cf'
CTO = '9a325906-292b-49ed-9bef-4d639f12366c'


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS qa_cleanup_followups(task_id TEXT PRIMARY KEY,config TEXT,state TEXT,next_try REAL)')


def accepted_continuation(con, bound):
    """Absence alone cannot invent either an accepted QA or a historical hold."""
    request = bound['failed_execution']['request']
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'u3_qa_reconciliations', 'u3_deployment_assessments'} <= tables: return None
    row = con.execute('SELECT receipt FROM u3_qa_reconciliations WHERE task_id=?', (request['task_id'],)).fetchone()
    if not row: return None
    receipt = json.loads(row[0])
    if (receipt.get('source_sha') != request['source_sha']
            or receipt.get('failed_execution_receipt_sha256') != bound['failed_execution_sha256']
            or receipt.get('failed_browser_receipt_sha256') != bound['failed_browser_sha256']
            or receipt.get('historical_tdd_red') is not False): return None
    matches = []
    for row in con.execute('SELECT config,state FROM u3_deployment_assessments'):
        config, state = json.loads(row['config']), json.loads(row['state'])
        dossier = config.get('dossier', {})
        if (state.get('stage')=='evidence_assessment_accepted'
                and dossier.get('request_task') == request['task_id']
                and all(dossier.get(k)==v for k,v in receipt.items())
                and dossier.get('original_u3_historical_red_hold') is True
                and state.get('receipt', {}).get('evidence_sha256') == observer.digest(dossier)):
            matches.append(dict(config=config, state=state))
    if len(matches) != 1: return None
    return matches[0]


def instruction(config, role):
    return ('TECHNICAL DIAGNOSIS ONLY. Assess the immutable controller evidence in this issue. '
        'Cause: '+config['cause']+'. Do not claim execution, run tools, delete resources, '
        'repeat QA, waive historical Red, approve release, merge, or ask the CEO for a technical decision. '
        'For missing historical Red, recommend a genuine new test-first work item or preserve the hold; '
        'existing coverage cannot retroactively demonstrate TDD. Return action=request_correction '
        'with one bounded evidence-based next step, or action=escalate_cto. optional_files must be []. '
        'reason must be 1-1200 characters. CTO escalation cannot recurse. '
        'No proposal authorizes an execution. Role='+role+'.\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1')


def verdict(config, state, task):
    if (task.get('status') != 'completed' or task.get('agent_id') != state['target']
            or task.get('issue_id') != state['issue_id'] or task.get('wakeup_id') != state['wakeup_id']):
        raise ValueError('exact completed technical diagnostic required')
    raw = (task.get('result') or {}).get('output', '')
    if not isinstance(raw, str) or len(raw) > 3000: raise ValueError('bounded diagnostic required')
    value = json.loads(raw)
    if (set(value) != {'action', 'reason', 'optional_files'}
            or value['action'] not in ('request_correction', 'escalate_cto')
            or value['optional_files'] != [] or not isinstance(value['reason'], str)
            or not 1 <= len(value['reason']) <= 1200):
        raise ValueError('non-authorizing technical diagnostic required')
    return dict(decision=value, task_id=task['id'], evidence_sha256=observer.digest(config),
                release_homologated=False, historical_tdd_red=False, execution_authorized=False)


class Effects:
    def __init__(self, b):
        try:
            import native, handoff_runtime
            from incremental_provisioning import NativeIssues
        except ImportError:
            from broker import native, handoff_runtime
            from broker.incremental_provisioning import NativeIssues
        self.b, self.native = b, native
        self.settings = json.loads((b.STATE/'native.json').read_text())
        self.issues = NativeIssues(self.settings)
        self.runtime = handoff_runtime.Effects(b, self.settings)
    def ready(self, target):
        if self.settings['agents'].get(target) != 'planning': raise ValueError('planning-only technical role required')
        with self.b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone(): return False
        return self.runtime.remaining_calls() >= 8
    def issue(self, config, role):
        if config.get('accepted_assessment'):
            import assess_u3_deployment as assessment
            accepted = config['accepted_assessment']
            previous = self.native.task_record(self.settings, accepted['state']['receipt']['task_id'], accepted['config']['assessor'])
            if assessment.verdict(accepted['config'], accepted['state'], previous) != accepted['state']['receipt']:
                raise ValueError('accepted assessment native evidence drift')
        parent = self.issues.request('/issues/'+config['request']['issue_id'])
        visible = {k:v for k,v in config.items() if k!='accepted_assessment'}
        if config.get('accepted_assessment'):
            visible['accepted_assessment_ref'] = {k:config['accepted_assessment']['state']['receipt'][k]
                for k in ('task_id', 'assessor', 'evidence_sha256')}
        description = 'CONTROLLER DIAGNOSTIC ONLY\n'+json.dumps(visible, sort_keys=True)
        if len(description)>7500: raise ValueError('bounded diagnostic issue required')
        return self.issues.ensure(dict(title='QA technical incident '+observer.digest(config)[:12]+' '+role,
            description=description,
            parent_issue_id=parent['id'], project_id=parent.get('project_id'), stage=4, status='todo'))
    def wake(self, config, state):
        marker = observer.digest(dict(config=config, role=state['role']))
        return self.native.ensure_planning_start(self.settings, state['issue_id'], state['target'],
            config['request']['task_id'], marker, instruction(config, state['role']), allow_create=True)
    def task(self, state):
        tasks = [t for t in self.native.issue_task_runs(self.settings, state['issue_id'])
                 if t.get('wakeup_id') == state['wakeup_id']]
        if len(tasks) > 1: raise ValueError('duplicate technical diagnostic')
        return self.native.task_record(self.settings, tasks[0]['id'], state['target']) if tasks else None


def tick(b, *, effects=None, now=None):
    now = time.time() if now is None else now
    with b.db() as con:
        initialize(con)
        rows = con.execute('SELECT task_id,config,state FROM qa_cleanup_observations').fetchall()
        for row in rows:
            incident = json.loads(row['state']); bound = json.loads(row['config'])
            if incident['stage'] not in ('blocked', 'cleanup_absence_confirmed'): continue
            # Preserve one immutable followup per exact QA request; no repeated
            # escalation triggered by a later poll or a supervisor restart.
            request = bound['failed_execution']['request']
            accepted = accepted_continuation(con, bound) if incident['stage']=='cleanup_absence_confirmed' else None
            if incident['stage']=='cleanup_absence_confirmed' and not accepted:
                # Stay visible; no forged approval or ungrounded TDD diagnosis.
                continue
            config = dict(request=request, cleanup_state=incident['stage'],
                cause='historical_tdd_red_missing' if incident['stage']=='cleanup_absence_confirmed' else incident.get('category', 'cleanup_no_progress'),
                failed_execution_sha256=bound['failed_execution_sha256'],
                failed_browser_sha256=bound['failed_browser_sha256'],
                observer_evidence_sha256=observer.digest(bound),
                accepted_assessment=accepted,
                release_homologated=False, historical_tdd_red=False, execution_authorized=False)
            state = dict(stage='issue_intent', role='cto' if incident['owner']=='cto' or incident['stage']=='cleanup_absence_confirmed' else 'techlead',
                         attempts=0, at=now, execution_authorized=False)
            state['target'] = CTO if state['role']=='cto' else TECHLEAD
            con.execute('INSERT OR IGNORE INTO qa_cleanup_followups VALUES(?,?,?,?)',
                (row['task_id']+'/'+incident['stage'], json.dumps(config, sort_keys=True), json.dumps(state), now))
        row = con.execute('SELECT * FROM qa_cleanup_followups WHERE next_try<=? ORDER BY next_try LIMIT 1', (now,)).fetchone()
    if not row: return
    config, state = json.loads(row['config']), json.loads(row['state'])
    effects = effects or Effects(b)
    def save(delay=5):
        with b.db() as con:
            con.execute('UPDATE qa_cleanup_followups SET state=?,next_try=? WHERE task_id=?',
                        (json.dumps(state, sort_keys=True), now+delay, row['task_id']))
    try:
        if state['stage']=='issue_intent':
            if not effects.ready(state['target']):
                state['next_action']='Await worker capacity or authorized model budget'; save(30); return state
            issue = effects.issue(config, state['role'])
            state.update(stage='dispatch_intent', issue_id=issue['id'], identifier=issue['identifier']); save()
        if state['stage']=='dispatch_intent':
            if not effects.ready(state['target']): save(30); return state
            wake = effects.wake(config, state)
            state.update(stage='awaiting_diagnostic', wakeup_id=wake['id'], dispatched_at=now); save()
        if state['stage']=='awaiting_diagnostic':
            task = effects.task(state)
            if task and task['status'] not in ('queued','running','dispatched'):
                receipt = verdict(config, state, task)
                state.setdefault('diagnostics', []).append(receipt)
                if receipt['decision']['action']=='escalate_cto' and state['role']=='techlead':
                    state.update(stage='issue_intent', role='cto', target=CTO, attempts=0)
                    state.pop('wakeup_id', None); state.pop('issue_id', None); save(); return state
                state.update(stage='diagnostic_recorded' if receipt['decision']['action']=='request_correction' else 'technical_blocked',
                    next_action='Controller must validate changed evidence before any execution; release/TDD hold remains')
                save(1e30)
                print(json.dumps(dict(event='qa_technical_diagnostic_recorded', source_task=row['task_id'],
                    issue=state['identifier'], role=state['role'], stage=state['stage'], execution_authorized=False)), flush=True)
                return state
            if now-state['dispatched_at'] >= 1800:
                if state['role']=='techlead':
                    state.setdefault('diagnostics', []).append(dict(category='techlead_diagnostic_deadline',
                        wakeup_id=state['wakeup_id'], execution_authorized=False))
                    state.update(stage='issue_intent', role='cto', target=CTO, attempts=0)
                    state.pop('wakeup_id', None); state.pop('issue_id', None); save(); return state
                state.update(stage='technical_blocked', next_action='Diagnose stalled native task; no identical respawn'); save(1e30); return state
        save()
    except Exception as error:
        state['attempts'] += 1; state['category'] = type(error).__name__
        if isinstance(error, ValueError) or state['attempts'] >= 2:
            state.update(stage='technical_blocked', next_action='CTO reconciles native control-plane evidence; no identical retry'); save(1e30)
        else: save(30)
    return state
