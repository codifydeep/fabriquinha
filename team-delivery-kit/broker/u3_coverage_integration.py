"""Coverage-only preintegration. Never upgrades feature TDD or grants merge/deploy."""
import json
import time

try:
    import u3_product_intake as intake, u3_controls_execution as controls, native, handoff_runtime
except ImportError:
    from broker import u3_product_intake as intake, u3_controls_execution as controls, native, handoff_runtime


def approved(config, state, task, decision, reads):
    manifest = config['certificate']['controls_manifest_sha256']
    if (state.get('stage') != 'coverage_classification_approved'
            or state.get('product_admission_authorized') is not False
            or state.get('delivery_approval') is not False
            or task.get('id') != state.get('task_id')
            or task.get('agent_id') != config['cto']
            or task.get('issue_id') != config['issue_id']
            or task.get('wakeup_id') != state.get('wakeup_id')
            or task.get('status') != 'completed' or decision != state.get('decision')
            or decision.get('action') != 'approve_test_revision'
            or decision.get('manifest_sha256') != manifest or decision.get('optional_files') != []):
        raise ValueError('exact completed CTO coverage classification required')
    complete_reads(reads)
    return manifest


def complete_reads(reads):
    for path in intake.paths():
        value = reads.get(path, {})
        if (type(value.get('lines')) is not int or value['lines'] <= 0
                or value['lines'] != value.get('total_lines')):
            raise ValueError('complete immutable coverage reads required')


def contract(config, proof, reviewer):
    c = config['controls_config']
    if reviewer in (c['author'], config['cto']) or reviewer != c['reviewer']:
        raise ValueError('independent coverage integration reviewer required')
    if proof != config['proof']:
        raise ValueError('executed coverage evidence drift')
    result = dict(schema='u3-coverage-integration-v1', root=config['certificate']['root'],
        classification='existing_behavior_coverage_only', base_sha=proof['base_sha'],
        base_manifest_sha256=proof['base_manifest_sha256'],
        manifest_sha256=config['certificate']['controls_manifest_sha256'],
        new_test_sha256=proof['new_test_sha256'], reviewer=reviewer, author=c['author'],
        previous_files_unchanged=True, historical_tdd_red=False,
        product_admission_authorized=False, delivery_approval=False,
        merge_authorized=False, deploy_authorized=False)
    if (set(result['new_test_sha256']) != {'tests/test_incremental_u3.py', *controls.FILES.values()}
            or proof.get('previous_files_unchanged') is not True
            or proof.get('historical_tdd_red') is not False):
        raise ValueError('three additive tests with unchanged product required')
    return result


def review_receipt(config, state, task, decision, reads):
    if (task.get('agent_id') != config['reviewer'] or task.get('issue_id') != config['issue_id']
            or task.get('wakeup_id') != state['wakeup_id'] or task.get('status') != 'completed'
            or decision.get('action') != 'approve_test_revision'
            or decision.get('manifest_sha256') != config['contract']['manifest_sha256']
            or decision.get('optional_files') != []):
        raise ValueError('exact independent coverage integration decision required')
    complete_reads(reads)
    return dict(schema='u3-coverage-integration-review-v1', task_id=task['id'],
        reviewer=config['reviewer'], contract_sha256=intake.intake.digest(config['contract']),
        manifest_sha256=config['contract']['manifest_sha256'], decision=decision,
        read_evidence_sha256=intake.intake.digest(reads),
        integration_review_approved=True, delivery_approval=False,
        merge_authorized=False, deploy_authorized=False, historical_tdd_red=False)


def saved(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='u3_coverage_integrations'").fetchone():
            return None
        row = con.execute('SELECT config,state FROM u3_coverage_integrations WHERE source_task=?',
                          (controls.SOURCE,)).fetchone()
    return tuple(map(json.loads, row)) if row else None


def save(b, state):
    with b.db() as con:
        con.execute('UPDATE u3_coverage_integrations SET state=? WHERE source_task=?',
                    (json.dumps(state, sort_keys=True), controls.SOURCE))


def verify(b, settings, fx):
    config, state = intake.saved(b)
    c, current = controls.saved(b)
    if intake.qualify(c, current, config['proof']) != config['certificate']:
        raise ValueError('current coverage lineage required')
    with b.db() as con:
        intake.intake.verify(con, c['plan_config'])
    task = native.task_record(settings, state['task_id'], config['cto'])
    approved(config, state, task, fx.decision(task), fx.read_evidence(task))
    return config, state


def prepare(b, settings, fx):
    config, classification = verify(b, settings, fx)
    reviewer = config['controls_config']['reviewer']
    if settings['agents'].get(reviewer) != 'planning':
        raise ValueError('readonly independent reviewer required')
    labels = b.docker('GET', '/volumes/' + config['base']['volume'])['Labels']
    if labels.get('delivery-kit.owner') != b.OWNER or labels.get('delivery-kit.issue-id') != config['base']['issue_id']:
        raise ValueError('exact owned original coverage base required')
    proof = controls.job(b, '/u3_product_probe.py', [
        dict(Type='volume', Source=config['base']['volume'], Target='/base', ReadOnly=True),
        dict(controls.owned(b, config['seed']['snapshot'], config['seed']['task_id']), Target='/candidate')],
        ['BASE_MANIFEST=' + config['base']['manifest_sha256'],
         'CONTROLS_MANIFEST=' + config['seed']['manifest_sha256']])
    certificate = contract(config, proof, reviewer)
    try:
        from incremental_provisioning import NativeIssues
    except ImportError:
        from broker.incremental_provisioning import NativeIssues
    issues = NativeIssues(settings)
    parent = issues.request('/issues/' + config['issue_id'])
    child = issues.ensure(dict(title='U3 coverage integration review ' + intake.intake.digest(certificate)[:12],
        description='Readonly independent preintegration of three approved additive tests. '
            'Original product unchanged; full 261-test suite verified. No feature Red, merge, deploy or release authority.',
        parent_issue_id=config['issue_id'], project_id=parent.get('project_id'), stage=3, status='todo'))
    entry = dict(contract=certificate, intake=config, classification_task=classification['task_id'],
                 reviewer=reviewer, issue_id=child['id'], identifier=child.get('identifier'))
    state = dict(stage='awaiting_budget', minimum_calls=32, owner=reviewer,
                 delivery_approval=False, next_action='Independent readonly coverage integration review')
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS u3_coverage_integrations(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
        con.execute('INSERT INTO u3_coverage_integrations VALUES(?,?,?)',
                    (controls.SOURCE, json.dumps(entry, sort_keys=True), json.dumps(state, sort_keys=True)))


def tick(b):
    parent = intake.saved(b)
    if not parent or parent[1].get('stage') != 'coverage_classification_approved':
        return
    with b.LOCK:
        settings = json.loads((b.STATE / 'native.json').read_text())
        fx = handoff_runtime.Effects(b, settings)
        entry = saved(b)
        if not entry:
            # Preparation has no model calls and is idempotent by stable issue title.
            try:
                prepare(b, settings, fx)
            except Exception as error:
                with b.db() as con:
                    con.execute('CREATE TABLE IF NOT EXISTS u3_coverage_integrations(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
                    con.execute('INSERT OR IGNORE INTO u3_coverage_integrations VALUES(?,?,?)',
                        (controls.SOURCE, json.dumps(dict(intake=parent[0])), json.dumps(dict(
                            stage='blocked', category=type(error).__name__, owner=parent[0]['cto'],
                            delivery_approval=False, next_action='CTO diagnoses preparation failure; no identical retry'))))
            return
        config, state = entry
        if state['stage'] in ('blocked', 'integration_review_approved'):
            return
        try:
            current, classification = verify(b, settings, fx)
            if (current != config['intake'] or classification['task_id'] != config['classification_task']
                    or contract(current, current['proof'], config['reviewer']) != config['contract']):
                raise ValueError('coverage integration contract drift')
            if state['stage'] == 'awaiting_budget':
                if fx.remaining_calls() < state['minimum_calls']:
                    return
                manifest = config['contract']['manifest_sha256']
                note = ('INDEPENDENT COVERAGE INTEGRATION REVIEW ONLY. Read all original and candidate files. '
                    'Three additive test files, unchanged original product and previous tests; '
                    'controller verified baseline255 and complete261. CTO classification is coverage-only. '
                    'Verify regression coverage and safe additive integration; approve_test_revision or '
                    'reject_test_revision with specific finding, optional_files=[]. No writes or tools escalation, '
                    'no historical Red, feature completion, PR merge, deploy or release authority.\n'
                    'DELIVERY_STRUCTURED_DECISION_V1:test_review:' + manifest + '\n'
                    'DELIVERY_TYPED_REVIEW_V1:' + manifest + '\nDELIVERY_DETERMINISTIC_READ_V1\n'
                    + ''.join('DELIVERY_REVIEW_READ_PATH:' + p + '\n' for p in intake.paths()))
                wake = fx.ensure_planning_start(config['issue_id'], config['reviewer'],
                    config['intake']['seed']['task_id'], intake.intake.digest(dict(contract=config['contract'], note=note)),
                    note, allow_create=True)
                state.update(stage='awaiting_review', wakeup_id=wake['id'], at=time.time())
                save(b, state)
                return
            runs = [t for t in native.issue_task_runs(settings, config['issue_id'])
                    if t.get('wakeup_id') == state['wakeup_id'] and t.get('agent_id') == config['reviewer']]
            if len(runs) > 1:
                raise ValueError('duplicate independent coverage reviews')
            if not runs or runs[0]['status'] in ('queued', 'running', 'dispatched'):
                if time.time() - state['at'] > 1800:
                    raise TimeoutError('coverage integration review deadline')
                return
            task = runs[0]
            receipt = review_receipt(config, state, task, fx.decision(task), fx.read_evidence(task))
            state.update(stage='integration_review_approved', receipt=receipt,
                next_action='Protected additive PR preparation; CI, independent delivery review and deploy/QA still required')
            save(b, state)
        except handoff_runtime.BudgetStatusUnavailable:
            return
        except Exception as error:
            state.update(stage='blocked', category=type(error).__name__, owner=current['cto'] if 'current' in locals() else parent[0]['cto'],
                next_action='CTO diagnoses exact integration failure; no identical retry or implicit merge')
            save(b, state)


def mounts(b, binding):
    entry = saved(b)
    if not entry:
        return []
    config, state = entry
    if (state['stage'] != 'awaiting_review' or binding['issue_id'] != config['issue_id']
            or binding['agent_id'] != config['reviewer']):
        return []
    with b.db() as con:
        row = con.execute('SELECT task_id FROM native_bindings WHERE request_id=?', (binding['request_id'],)).fetchone()
    task = native.task_record(json.loads((b.STATE / 'native.json').read_text()), row['task_id'], config['reviewer'])
    if task.get('wakeup_id') != state['wakeup_id']:
        raise ValueError('exact coverage integration wake required')
    source = config['intake']
    labels = b.docker('GET', '/volumes/' + source['base']['volume'])['Labels']
    if labels.get('delivery-kit.owner') != b.OWNER or labels.get('delivery-kit.issue-id') != source['base']['issue_id']:
        raise ValueError('coverage original base ownership drift')
    return [dict(controls.owned(b, source['seed']['snapshot'], source['seed']['task_id']), Target='/evidence/candidate'),
            dict(Type='volume', Source=source['base']['volume'], Target='/evidence/previous', ReadOnly=True)]
