"""Exact published coverage review. Does not admit a feature or authorize a release."""
import hashlib
import json
import time
import urllib.request

try:
    import native, handoff_runtime, u3_coverage_integration as integration
    import u3_controls_execution as controls
except ImportError:
    from broker import native, handoff_runtime, u3_coverage_integration as integration
    from broker import u3_controls_execution as controls

REVIEWER = 'f3ec2af2-216b-4210-81aa-4c4bc48bf292'
HEAD = 'c7ff21c72cd2bd6eb97633d6e9dedce127b2ee3d'
BASE = '5e35f58109f9f48ff61ea05dbfd0e1a7775aca07'
PR = 'https://github.com/codifydeep/descartavel2/pull/36'
PATHS = tuple('/delivery/' + p for p in (*controls.SOURCES, *controls.FILES.values()))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def saved(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='u3_delivery_reviews'").fetchone():
            return None
        row = con.execute('SELECT config,state FROM u3_delivery_reviews WHERE source_task=?',
                          (controls.SOURCE,)).fetchone()
    return tuple(map(json.loads, row)) if row else None


def save(b, state):
    with b.db() as con:
        con.execute('UPDATE u3_delivery_reviews SET state=? WHERE source_task=?',
                    (json.dumps(state, sort_keys=True), controls.SOURCE))


def manages_source(b, task):
    entry = saved(b)
    if not entry:
        return False
    parent = integration.saved(b)
    return bool(parent and parent[0]['intake']['seed']['task_id'] == task)


def qualify(config, parent, state, settings):
    publication = state.get('publication', {})
    if (state.get('stage') != 'integration_review_approved'
            or publication.get('coverage_head_sha') != HEAD
            or publication.get('coverage_pr') != PR
            or publication.get('coverage_ci') != 'success'
            or publication.get('predecessor_merged_sha') != BASE
            or publication.get('predecessor_main_ci') != 'success'
            or publication.get('merge_authorized') is not False
            or config['parent_contract_sha256'] != digest(parent['contract'])
            or config['parent_review_sha256'] != digest(state['receipt'])
            or config['manifest_sha256'] != parent['contract']['manifest_sha256']
            or config['head_sha'] != HEAD or config['base_sha'] != BASE
            or config['pr_url'] != PR or config['reviewer'] != REVIEWER
            or settings['agents'].get(REVIEWER) != 'review'
            or REVIEWER in (parent['reviewer'], parent['intake']['controls_config']['author'],
                           parent['intake']['cto'])):
        raise ValueError('exact published independent coverage review required')


def current(b, config):
    parent, state = integration.saved(b)
    settings = json.loads((b.STATE / 'native.json').read_text())
    qualify(config, parent, state, settings)
    fx = handoff_runtime.Effects(b, settings)
    actual, classification = integration.verify(b, settings, fx)
    if actual != parent['intake'] or classification['task_id'] != parent['classification_task']:
        raise ValueError('coverage classification lineage drift')
    task = native.task_record(settings, state['receipt']['task_id'], parent['reviewer'])
    if integration.review_receipt(parent, state, task, fx.decision(task), fx.read_evidence(task)) != state['receipt']:
        raise ValueError('actual preintegration review drift')
    return parent, settings, fx


def begin(b):
    """Operator admission only; no worker endpoint. Stable title makes crash recovery safe."""
    with b.LOCK:
        prior = saved(b)
        if prior:
            current(b, prior[0])
            return prior[1]
        parent, state = integration.saved(b)
        config = dict(parent_contract_sha256=digest(parent['contract']),
            parent_review_sha256=digest(state['receipt']), manifest_sha256=parent['contract']['manifest_sha256'],
            head_sha=HEAD, base_sha=BASE, pr_url=PR, reviewer=REVIEWER)
        current(b, config)
        from incremental_provisioning import NativeIssues
        settings = json.loads((b.STATE / 'native.json').read_text())
        issues = NativeIssues(settings)
        owner = issues.request('/issues/' + parent['issue_id'])
        child = issues.ensure(dict(title='U3 final immutable delivery review ' + HEAD[:12],
            description='Independent review-mode approval of PR36 exact SHA and immutable snapshot. '
                'Controlled complete suite; existing-behavior coverage only. No historical Red or release authority.',
            parent_issue_id=parent['issue_id'], project_id=owner.get('project_id'), stage=3, status='todo'))
        config.update(issue_id=child['id'], identifier=child.get('identifier'))
        pending = dict(stage='awaiting_budget', owner=REVIEWER, minimum_calls=32,
            delivery_approval=False, merge_authorized=False, deploy_authorized=False,
            next_action='Independent immutable delivery review and controller-owned complete suite')
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS u3_delivery_reviews(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
            con.execute('INSERT INTO u3_delivery_reviews VALUES(?,?,?)',
                        (controls.SOURCE, json.dumps(config, sort_keys=True), json.dumps(pending, sort_keys=True)))
            con.execute('INSERT INTO issue_test_commands VALUES(?,?)',
                        (config['issue_id'], controls.controls_test_command()))
        return pending


def job_request(b,config,state,source,request):
    with b.db() as con:
        rows=con.execute('SELECT n.task_id,n.request_id,s.status FROM native_bindings n '
            'JOIN review_bindings r USING(request_id) JOIN review_suite_rpc s USING(request_id) '
            'WHERE n.issue_id=? AND n.agent_id=? AND r.source_task_id=?',
            (config['issue_id'],config['reviewer'],source)).fetchall()
    settings=json.loads((b.STATE/'native.json').read_text())
    matches=[]
    for row in rows:
        if request and row['request_id']!=request:continue
        if not request and row['status']!='passed':continue
        task=native.task_record(settings,row['task_id'],config['reviewer'])
        if task.get('wakeup_id')==state['wakeup_id'] and task.get('issue_id')==config['issue_id']:
            matches.append(row['request_id'])
    if len(matches)!=1:raise ValueError('one exact execution-scoped coverage validation required')
    return matches[0]


def validate(b, volume, source_task_id, *, suite_evidence=False, review_request_id=None):
    entry = saved(b)
    if not entry:
        return None
    config, state = entry
    parent, _ = integration.saved(b)
    seed = parent['intake']['seed']
    if source_task_id != seed['task_id'] or volume != seed['snapshot']['volume']:
        return None
    if state['stage'] not in ('awaiting_review', 'delivery_review_approved'):
        raise ValueError('coverage suite has no active final review')
    parent, _, _ = current(b, config)
    base = parent['intake']['base']
    labels = b.docker('GET', '/volumes/' + base['volume'])['Labels']
    if labels.get('delivery-kit.owner') != b.OWNER or labels.get('delivery-kit.issue-id') != base['issue_id']:
        raise ValueError('original coverage base ownership drift')
    controls.owned(b, seed['snapshot'], seed['task_id'])
    request=job_request(b,config,state,source_task_id,review_request_id)
    try:import durable_review_job
    except ImportError:from broker import durable_review_job
    job=durable_review_job.run(b,request,base,seed,parent['intake']['proof'])
    proof=job['proof']
    if proof != parent['intake']['proof']:
        raise ValueError('complete coverage suite or snapshot drift')
    result = dict(manifest_sha256=config['manifest_sha256'], tests=261, baseline_tests_intact=True,
        portable=True, classification='existing_behavior_coverage_only', historical_tdd_red=False,
        product_admission_authorized=False)
    if suite_evidence:
        result['suite'] = dict(tests=261, output=job['output'],output_sha256=job['output_sha256'],
            test_image=job['image'], test_command=['python', '/u3_product_probe.py'],
            validation_job_key=job['job_key'],validation_contract_sha256=job['contract_sha256'])
    return result


def authorize_binding(b, binding):
    """A child review consumes its registered parent snapshot, never a fake child Git base."""
    entry = saved(b)
    if not entry or binding.get('issue_id') != entry[0]['issue_id']:
        return False
    config, state = entry
    if (binding.get('mode') != 'review' or binding.get('agent_id') != config['reviewer']
            or state['stage'] != 'awaiting_review' or binding.get('wakeup_id') != state['wakeup_id']):
        raise ValueError('exact final review native binding required')
    parent, _, _ = current(b, config)
    seed = parent['intake']['seed']
    controls.owned(b, seed['snapshot'], seed['task_id'])
    b.assign_review(dict(source_task_id=seed['task_id'], review_agent_id=config['reviewer']))
    return True


def read_contract(b,request_id):
    """Only the registered child/wake receives this controller-owned read list."""
    entry=saved(b)
    if not entry:return None
    config,state=entry
    with b.db() as con:
        row=con.execute('SELECT n.issue_id,n.agent_id,n.task_id,g.mode FROM native_bindings n '
                        'JOIN grants g USING(request_id) WHERE request_id=?',
                        (request_id,)).fetchone()
    if not row or row['issue_id']!=config['issue_id']:return None
    if (state['stage']!='awaiting_review' or row['agent_id']!=config['reviewer']
            or row['mode']!='review'):
        raise ValueError('exact final review read contract binding required')
    settings=json.loads((b.STATE/'native.json').read_text())
    task=native.task_record(settings,row['task_id'],config['reviewer'])
    if task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']:
        raise ValueError('exact final review read contract binding required')
    return list(PATHS)


def require_complete_reads(reads):
    for path in PATHS:
        value=reads.get(path,{})
        if type(value.get('lines')) is not int or value['lines']<=0 or value['lines']!=value.get('total_lines'):
            raise ValueError('complete delivery reads required')


def read_recovery_evidence(config,state,task,decisions,suite,reads,canary):
    if (state.get('stage')!='blocked' or state.get('reason')!='complete delivery reads required'
            or 'read_recovery' in state or task.get('status')!='completed'
            or task.get('agent_id')!=config['reviewer'] or task.get('issue_id')!=config['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id'] or decisions!=['APPROVE']
            or suite.get('review_task')!=task['id'] or suite.get('manifest_sha256')!=config['manifest_sha256']
            or suite.get('exit_code')!=0 or suite.get('tests')!=261
            or suite.get('executed_by')!='controller_offline_review_suite'
            or suite.get('network')!='none' or suite.get('snapshot_mount')!='readonly'):
        raise ValueError('specific incomplete-read recovery required')
    try:require_complete_reads(reads)
    except ValueError:pass
    else:raise ValueError('incomplete read evidence required')
    if (canary.get('schema')!='u3-review-read-canary-v1' or canary.get('status')!='passed'
            or canary.get('model_calls')!=0 or canary.get('early_suite_denied') is not True
            or canary.get('inputs_unchanged') is not True or canary.get('network')!='none'
            or canary.get('delivery_approval') is not False or canary.get('large_pages',0)<1
            or not 0<canary.get('pages',0)<=128 or set(canary.get('files_sha256',{}))!=set(PATHS)):
        raise ValueError('real bounded read canary required')
    require_complete_reads(canary.get('complete_reads',{}))
    return dict(failed_task=task['id'],failed_wakeup=state['wakeup_id'],
        cause='delivery_acp_5k_display_cut',canary_sha256=digest(canary),
        head_sha=config['head_sha'],manifest_sha256=config['manifest_sha256'],delivery_approval=False)


def resume_reads(b):
    """One operator-admitted recovery; real registry canary must pass first."""
    with b.LOCK:
        config,state=saved(b)
        if 'read_recovery' in state:return state
        parent,settings,fx=current(b,config)
        tasks=tasks_for_wake(settings,config,state)
        if len(tasks)!=1:raise ValueError('one exact failed read review required')
        task=tasks[0]
        with b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle read recovery required')
            rows=con.execute('SELECT s.status,s.receipt FROM review_suite_rpc s '
                'JOIN native_bindings n USING(request_id) WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',
                (task['id'],config['issue_id'],config['reviewer'])).fetchall()
        if len(rows)!=1 or rows[0]['status']!='passed':raise ValueError('previous exact passed suite required')
        suite=json.loads(rows[0]['receipt'])
        decisions=b.review_decisions(native.task_messages(settings,task['id']))
        reads=fx.read_evidence(task)
        if state.get('stage')!='blocked' or state.get('reason')!='complete delivery reads required':
            raise ValueError('specific incomplete-read recovery required')
        # Fixed script/argv, exact owned snapshot, no credentials or socket.
        seed=parent['intake']['seed']
        mount=controls.owned(b,seed['snapshot'],seed['task_id']);mount['Target']='/delivery'
        image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
        if 'read_canary' not in state:
            canary=controls.job(b,'/review_read_canary.py',[mount],[
                'DELIVERY_EXECUTION_MODE=review','HOME=/tmp','HERMES_HOME=/tmp/hermes',
                'DELIVERY_REVIEW_READ_PATHS_JSON='+json.dumps(list(PATHS)),
                'DELIVERY_TEST_COMMANDS_JSON='+json.dumps([controls.controls_test_command()])])
            state['read_canary']=dict(image=image,snapshot=seed['snapshot'],result=canary)
            save(b,state)  # Restart between canary and wake must not rerun the probe.
        probe=state['read_canary']
        if probe['image']!=image or probe['snapshot']!=seed['snapshot']:
            raise ValueError('current-image exact-snapshot read canary required')
        canary=probe['result']
        for path,sha in parent['intake']['proof']['new_test_sha256'].items():
            if canary['files_sha256'].get('/delivery/'+path)!=sha:raise ValueError('canary delivery hash drift')
        certificate=read_recovery_evidence(config,state,task,decisions,suite,reads,canary)
        certificate.update(image=image,at=time.time())
        state.update(stage='awaiting_budget',owner=config['reviewer'],read_recovery=certificate,
            delivery_approval=False,next_action='One independent review with bounded complete delivery reads')
        for key in ('reason','category','terminal_seen_at'):state.pop(key,None)
        save(b,state)
        return state


def tasks_for_wake(settings, config, state):
    tasks = [t for t in native.issue_task_runs(settings, config['issue_id'])
             if t.get('agent_id') == config['reviewer'] and t.get('wakeup_id') == state['wakeup_id']]
    # Multica's task-runs projection omits pre-session bootstrap failures.
    # The consumed wakeup's exact native task is still authoritative.
    request = urllib.request.Request('http://backend:8080/api/issues/' + config['issue_id'] + '/wakeups',
        headers={'Authorization':'Bearer '+settings['token'],'X-Workspace-ID':settings['workspace_id']})
    with urllib.request.urlopen(request, timeout=5) as response:
        wakes = json.load(response)
    exact = [w for w in wakes if w.get('id') == state['wakeup_id']]
    if len(exact) != 1 or exact[0].get('agent_id') != config['reviewer']:
        raise ValueError('exact final review wakeup required')
    task_id = exact[0].get('last_task_id')
    if task_id and not any(t['id'] == task_id for t in tasks):
        task = native.task_record(settings, task_id, config['reviewer'])
        if task.get('issue_id') != config['issue_id'] or task.get('wakeup_id') != state['wakeup_id']:
            raise ValueError('consumed wake task ownership drift')
        tasks.append(task)
    return tasks


def resume_bootstrap(b):
    """One explicit recovery after correcting the proven zero-tool bootstrap cause."""
    with b.LOCK:
        config, state = saved(b)
        parent, settings, _ = current(b, config)
        tasks = tasks_for_wake(settings, config, state)
        if len(tasks) != 1 or state.get('bootstrap_recovery'):
            raise ValueError('one nonrepeated bootstrap failure required')
        task = tasks[0]
        if (task['status'] != 'failed' or task.get('error') != 'hermes initialize failed: hermes process exited'
                or native.task_messages(settings, task['id'])):
            raise ValueError('exact zero-tool review bootstrap failure required')
        with b.db() as con:
            if con.execute('SELECT 1 FROM native_bindings WHERE task_id=?', (task['id'],)).fetchone():
                raise ValueError('execution already reached broker; bootstrap recovery forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle bootstrap repair required')
        state['bootstrap_recovery'] = dict(failed_task=task['id'], failed_wakeup=state['wakeup_id'],
            cause='child_review_missing_registered_base_and_parent_snapshot_binding',
            fix='exact_child_review_parent_snapshot_authorization_v1',
            previous_blocker={k:state[k] for k in ('category','reason','next_action') if k in state}, at=time.time())
        state.update(stage='awaiting_budget', owner=config['reviewer'], delivery_approval=False,
            next_action='One corrected immutable review bootstrap; previous failed task remains preserved')
        for key in ('category','reason'):
            state.pop(key, None)
        state.pop('terminal_seen_at', None)
        save(b, state)
        return state


def recovery_evidence(config,state,task,decisions,rpc,probe,proof):
    receipt=probe.get('job_receipt',{})
    if (state.get('stage')!='blocked' or 'infrastructure_recovery' in state
            or task.get('status')!='completed' or task.get('agent_id')!=config['reviewer']
            or task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']
            or decisions!=['REQUEST_CHANGES'] or rpc.get('status')!='failed'
            or json.loads(rpc['receipt']).get('error_type')!='DockerOperationTimeout'
            or probe.get('schema')!='u3-durable-review-canary-v1'
            or probe.get('head_sha')!=config['head_sha'] or probe.get('manifest_sha256')!=config['manifest_sha256']
            or probe.get('model_calls')!=0 or probe.get('creates')!=1 or probe.get('starts')!=1
            or probe.get('delivery_approval') is not False
            or receipt.get('schema')!='durable-coverage-job-receipt-v1' or receipt.get('proof')!=proof
            or 'start_response_timeout' not in receipt.get('recovered_events',[])
            or receipt.get('network')!='none' or receipt.get('snapshot_mount')!='readonly'):
        raise ValueError('exact infrastructure failure and new durable recovery evidence required')
    return dict(failed_task=task['id'],failed_wakeup=state['wakeup_id'],
        diagnosis='docker_response_timeout_not_product_regression',probe_sha256=digest(probe),
        validation_job_key=receipt['job_key'],head_sha=config['head_sha'],manifest_sha256=config['manifest_sha256'],
        delivery_approval=False,at=time.time())


def resume_infrastructure(b):
    """Admission after real fault-recovery canary; old RPC/verdict are never rewritten."""
    with b.LOCK:
        config,state=saved(b)
        if 'infrastructure_recovery' in state:return state
        parent,settings,_=current(b,config)
        tasks=tasks_for_wake(settings,config,state)
        if len(tasks)!=1:raise ValueError('one exact failed review required')
        task=tasks[0]
        with b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle infrastructure recovery required')
            rows=con.execute('SELECT s.status,s.receipt FROM review_suite_rpc s '
                'JOIN native_bindings n USING(request_id) WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',
                (task['id'],config['issue_id'],config['reviewer'])).fetchall()
        if len(rows)!=1:raise ValueError('one exact failed validation capability required')
        probe=json.loads((b.STATE/'u3-review-durable-canary.json').read_text())
        certificate=recovery_evidence(config,state,task,b.review_decisions(native.task_messages(settings,task['id'])),
                                      dict(rows[0]),probe,parent['intake']['proof'])
        try:import durable_review_job
        except ImportError:from broker import durable_review_job
        entry=durable_review_job.saved(b,certificate['validation_job_key'])
        if (not entry or entry[1]['phase']!='passed' or entry[1]['receipt']!=probe['job_receipt']
                or entry[0]['base']!=parent['intake']['base'] or entry[0]['seed']!=parent['intake']['seed']
                or entry[0]['image']!=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']):
            raise ValueError('real current-image durable canary required')
        certificate['previous_blocker']={k:state[k] for k in ('reason','category','next_action') if k in state}
        state.update(stage='awaiting_budget',owner=config['reviewer'],infrastructure_recovery=certificate,
                     delivery_approval=False,next_action='One new independent review after verified durable Docker recovery')
        for key in ('reason','category','terminal_seen_at'):state.pop(key,None)
        save(b,state)
        return state


def receipt(config, state, task, review, suite, reads, source):
    if (task.get('status') != 'completed' or task.get('agent_id') != config['reviewer']
            or task.get('issue_id') != config['issue_id'] or task.get('wakeup_id') != state['wakeup_id']
            or review.get('review_task_id') != task['id'] or review.get('status') != 'approved'
            or review.get('source_task_id') != source or review.get('reviewer_agent_id') != config['reviewer']
            or review.get('manifest_sha256') != config['manifest_sha256']
            or suite.get('review_task') != task['id'] or suite.get('source_task') != source
            or suite.get('manifest_sha256') != config['manifest_sha256']
            or suite.get('tests') != 261 or suite.get('exit_code') != 0
            or suite.get('executed_by') != 'controller_offline_review_suite'
            or suite.get('network') != 'none' or suite.get('snapshot_mount') != 'readonly'):
        raise ValueError('exact independent native approval and suite evidence required')
    require_complete_reads(reads)
    return dict(schema='u3-final-coverage-review-v1', head_sha=config['head_sha'], base_sha=config['base_sha'],
        pr_url=config['pr_url'], manifest_sha256=config['manifest_sha256'], source_task=source,
        review_task=task['id'], reviewer=config['reviewer'], suite_sha256=digest(suite),
        reads_sha256=digest(reads), delivery_approval=True, historical_tdd_red=False,
        product_admission_authorized=False, merge_authorized=False, deploy_authorized=False)


def tick(b):
    entry = saved(b)
    if not entry or entry[1]['stage'] in ('blocked', 'delivery_review_approved'):
        return
    with b.LOCK:
        config, state = entry
        try:
            parent, settings, fx = current(b, config)
            seed = parent['intake']['seed']
            if state['stage'] == 'awaiting_budget':
                if fx.remaining_calls() < state['minimum_calls']:
                    return
                b.assign_review(dict(source_task_id=seed['task_id'], review_agent_id=config['reviewer']))
                command = controls.controls_test_command().replace('/workspace', '/delivery')
                note = ('FINAL INDEPENDENT DELIVERY REVIEW. PR36 SHA ' + HEAD + ', snapshot '
                    + config['manifest_sha256'] + '. Existing-behavior coverage only, not feature TDD. '
                    'Read each listed file completely with read_file offset=1 limit=100, then consecutive '
                    '100-line pages until total_lines. Every call must have explicit offset and limit <=100. '
                    'Never infer completion from a preview or a truncated page:\n'
                    + '\n'.join(PATHS) + '\nRun the controller-owned complete suite once with terminal command: '
                    + command + '\nReview preserved tests and all three added regression tests. '
                    'No edits, Red replay, arbitrary terminal, network or administrative tools. '
                    'Finish with one standalone line Decision: APPROVE or Decision: REQUEST_CHANGES, '
                    'and concrete findings. Do not request implementation or claim deployment/release success.')
                wake = native.ensure_review_start(settings, config['issue_id'], config['reviewer'],
                    seed['task_id'], digest(dict(config=config, note=note,
                        bootstrap_recovery=state.get('bootstrap_recovery'),
                        infrastructure_recovery=state.get('infrastructure_recovery'),
                        read_recovery=state.get('read_recovery'))), note, allow_create=True)
                state.update(stage='awaiting_review', wakeup_id=wake['id'], at=time.time())
                save(b, state)
                return
            tasks = tasks_for_wake(settings, config, state)
            if len(tasks) > 1:
                raise ValueError('duplicate final delivery reviews')
            if not tasks or tasks[0]['status'] in ('queued', 'running', 'dispatched'):
                if time.time() - state['at'] > 1800:
                    raise TimeoutError('final delivery review deadline; CTO diagnosis required')
                return
            task = tasks[0]
            with b.db() as con:
                review = con.execute('SELECT * FROM reviews WHERE review_task_id=?', (task['id'],)).fetchone()
                rpc = con.execute('SELECT s.status,s.receipt FROM review_suite_rpc s JOIN native_bindings n '
                    'USING(request_id) WHERE n.task_id=?', (task['id'],)).fetchone()
            if not review or not rpc or rpc['status'] != 'passed':
                if task['status'] == 'completed' and (not review or not rpc):
                    # Native completion may precede closing the broker lease.
                    # Bounded observation is not another model execution.
                    first = state.setdefault('terminal_seen_at', time.time())
                    if time.time() - first < 60:
                        save(b, state)
                        return
                raise ValueError('completed native review lacks terminal approval or successful controlled suite')
            proof = receipt(config, state, task, dict(review), json.loads(rpc['receipt']),
                            fx.read_evidence(task), seed['task_id'])
            state.update(stage='delivery_review_approved', receipt=proof, delivery_approval=True,
                next_action='Revalidate exact GitHub SHA, CI and protection before protected integration; deploy/QA pending')
            save(b, state)
        except handoff_runtime.BudgetStatusUnavailable:
            return
        except Exception as error:
            state.update(stage='blocked', owner=parent['intake']['cto'] if 'parent' in locals() else 'cto',
                category=type(error).__name__, reason=str(error)[:300], delivery_approval=False,
                next_action='CTO diagnoses final review; no identical retry or implicit approval')
            save(b, state)
