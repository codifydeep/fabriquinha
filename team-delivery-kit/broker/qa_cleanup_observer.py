"""Controller-only durable observation of uncertain fixed-QA cleanup.

No DELETE/POST, model call or delivery approval. An absence certificate only
resolves resource uncertainty; functional QA, assessment and TDD stay separate.
There is intentionally no worker/API entrypoint for enrollment.
"""
import hashlib
import json
import re
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS qa_cleanup_observations('
                'task_id TEXT PRIMARY KEY,config TEXT,state TEXT,next_try REAL)')


def register(b, packet):
    try:
        import execute_u3_qa as qa
        import native
    except ImportError:
        import execute_u3_qa as qa
        from broker import native
    failed = packet['failed_execution']; proof = packet['failed_browser']
    request = failed.get('request', {}); owner = proof.get('owner', '')
    resources = [['network', owner], ['container', owner+'-app'], ['container', owner+'-browser']]
    if (set(packet) != {'failed_execution', 'failed_browser', 'failed_execution_sha256', 'failed_browser_sha256'}
            or b.PREFIX != 'delivery-kit-port2' or failed.get('stage') != 'blocked'
            or failed.get('reason') != 'post-deploy browser QA  cleanup: browser QA cleanup timeout; absence unproven'
            or not re.fullmatch(r'delivery-kit-browser-[a-f0-9]{32}', owner)
            or proof.get('resources') != resources or proof.get('status') != 'failed'
            or proof.get('cleanup') != 'failed' or not proof.get('error', '').startswith(' cleanup: ')
            or proof.get('automated') is not True
            or proof.get('result', {}).get('status') != 'passed'
            or proof['result'].get('contexts') != 2 or proof['result'].get('source_sha') != qa.SHA
            or len(proof['result'].get('checks', [])) != 40
            or any(not re.fullmatch(r'[a-f0-9]{64}', packet.get(k, '')) for k in
                   ('failed_execution_sha256', 'failed_browser_sha256'))
            or not re.fullmatch(r'[a-f0-9]{64}', proof.get('screenshot_sha256', ''))):
        raise ValueError('fixed cleanup-only evidence required')
    settings = json.loads((b.STATE/'native.json').read_text())
    task = native.task_record(settings, request['task_id'], qa.ASSESSOR)
    with b.db() as con:
        initialize(con)
        row = con.execute('SELECT config,state FROM u3_qa_executions WHERE evidence_sha256=?',
                          (request['evidence_sha256'],)).fetchone()
        if not row: raise ValueError('persisted fixed QA request required')
        config, state = json.loads(row['config']), json.loads(row['state'])
        verified = qa.request_receipt(config, state, task, json.loads(task['result']['output']))
        supplied = dict(request); supplied.pop('request_id', None)
        old = con.execute('SELECT config FROM u3_deployment_assessments WHERE evidence_sha256=?',
                          (request['evidence_sha256'],)).fetchone()
        if not old: raise ValueError('verified deployment dossier required')
        dossier = json.loads(old['config'])['dossier']; identity = proof.get('identity', {})
        if (verified != supplied or state.get('request') != request
                or dossier.get('source_sha') != qa.SHA or identity.get('source_sha') != qa.SHA
                or identity.get('application_image') != dossier.get('image')
                or identity.get('deployed_container_id') != dossier.get('container_id')
                or proof['result']['checks'] != dossier.get('browser_checks')):
            raise ValueError('native request or deployment evidence drift')
        bound = dict(packet, resources=resources, owner=owner)
        prior = con.execute('SELECT config FROM qa_cleanup_observations WHERE task_id=?',
                            (request['task_id'],)).fetchone()
        if prior and json.loads(prior['config']) != bound:
            raise ValueError('immutable cleanup incident drift')
        state = dict(stage='observing', at=time.time(), probes=0, errors=0, owner='devops',
                     next_action='Observe exact resources; never repeat uncertain deletion',
                     release_homologated=False, product_admission_authorized=False)
        con.execute('INSERT OR IGNORE INTO qa_cleanup_observations VALUES(?,?,?,?)',
                    (request['task_id'], json.dumps(bound, sort_keys=True), json.dumps(state), state['at']))
    return request['task_id']


def tick(b, *, now=None):
    now = time.time() if now is None else now
    with b.db() as con:
        initialize(con)
        row = con.execute('SELECT * FROM qa_cleanup_observations WHERE next_try<=? ORDER BY next_try LIMIT 1',
                          (now,)).fetchone()
    if not row: return
    state, config = json.loads(row['state']), json.loads(row['config'])
    if state['stage'] != 'observing': return
    event = None
    # All Docker I/O outside LOCK / transaction. Safe across interrupted probes:
    # only read-only, exact resource observations are repeated.
    try:
        if not b.docker('GET', '/version'): raise RuntimeError('Docker health unavailable')
        remaining = []
        for kind, name in config['resources']:
            path = '/networks/'+name if kind == 'network' else '/containers/'+name+'/json'
            info = b.docker('GET', path)
            if info is None: continue
            labels = info.get('Labels', {}) if kind == 'network' else info.get('Config', {}).get('Labels', {})
            if labels.get('delivery-kit.browser-qa') != config['owner']:
                raise ValueError('resource identity changed; retain foreign resource')
            remaining.append([kind, name])
        state.update(probes=state['probes']+1, errors=0, remaining=remaining)
        if not remaining:
            state.update(stage='cleanup_absence_confirmed', receipt=dict(
                schema='fixed-qa-cleanup-observation-v1', task_id=row['task_id'],
                source_sha=config['failed_execution']['request']['source_sha'],
                evidence_sha256=digest(config), resources_absent=config['resources'],
                failed_execution_sha256=config['failed_execution_sha256'],
                failed_browser_sha256=config['failed_browser_sha256'],
                tests_reexecuted=False, deletion_repeated=False, model_calls=0,
                release_homologated=False, product_admission_authorized=False,
                independent_agent_qa_approval=False),
                next_action='Reconcile QA evidence and independent assessment; preserve TDD/release holds')
            event = 'qa_cleanup_absence_confirmed'
        elif now-state['at'] >= 1800:
            state.update(stage='blocked', owner='techlead', category='cleanup_no_progress',
                         next_action='Diagnose Docker resource state; escalate technical decision to CTO')
            event = 'qa_cleanup_escalated'
        elif now-state['at'] >= 600 and not state.get('alerted'):
            state['alerted'] = True; event = 'qa_cleanup_alert'
    except Exception as error:
        state['errors'] += 1; state['category'] = type(error).__name__
        if isinstance(error, ValueError) or state['errors'] >= 2 or now-state['at'] >= 1800:
            state.update(stage='blocked', owner='cto', next_action='Diagnose observation failure; no identical retry')
            event = 'qa_cleanup_escalated'
    delay = min(60, 5 * 2 ** min(state['probes']+state['errors'], 4))
    with b.db() as con:
        con.execute('UPDATE qa_cleanup_observations SET state=?,next_try=? WHERE task_id=?',
                    (json.dumps(state, sort_keys=True), now+delay if state['stage']=='observing' else 1e30, row['task_id']))
    if event:
        print(json.dumps(dict(event=event, task_id=row['task_id'], stage=state['stage'],
                              owner=state['owner'], next_action=state['next_action'])), flush=True)
    return state


def run(b):
    while True:
        try:
            tick(b)
            try: import qa_cleanup_handoff
            except ImportError: from broker import qa_cleanup_handoff
            qa_cleanup_handoff.tick(b)
            try: import u3_work_proposal
            except ImportError: from broker import u3_work_proposal
            u3_work_proposal.tick(b)
            try: import u3_lifecycle_reconciliation
            except ImportError: from broker import u3_lifecycle_reconciliation
            u3_lifecycle_reconciliation.tick(b)
            try: import lifecycle_publication
            except ImportError: from broker import lifecycle_publication
            lifecycle_publication.tick(b)
        except Exception:
            print('QA cleanup observer unavailable; durable incidents retained', flush=True)
        time.sleep(5)
