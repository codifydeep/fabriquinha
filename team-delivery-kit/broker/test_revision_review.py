"""Independent review of new test revisions before granting implementation.

The old issue and its Red are never edited. A child runs tests-only against
the same original Git base. Its new immutable Red is reviewed before any
product-code permission; final Green and delivery review still remain required.
"""
import hashlib
import json
import re
import time
import uuid
from artifact_read_evidence import observations


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS test_revision_trials('
                'issue_id TEXT PRIMARY KEY, parent_issue TEXT UNIQUE, config TEXT, state TEXT)')


def prepare_citation_recovery(state, red, task, reviewer, decision, paths):
    """One fresh immutable review; never repair or accept the invalid verdict."""
    prior=state.get('citation_recovery')
    if prior:
        if prior.get('failed_task')!=task['id']:
            raise ValueError('citation recovery already consumed')
        return state
    failure=state.get('review_failure') or {};reads=state.get('read_evidence') or {}
    if (state.get('status')!='blocked' or state.get('review_task') or state.get('decision')
            or state.get('reason')!='invalid_independent_test_review:ValueError'
            or failure.get('detail')!='finding quote not observed at exact line'
            or failure.get('task_id')!=task['id'] or task.get('status')!='completed'
            or task.get('agent_id')!=reviewer or task.get('wakeup_id')!=state.get('wakeup_id')
            or state.get('terminal_contract')!='typed-review-v1' or state.get('evidence_policy')!=1
            or state.get('source_task')!=red['task_id'] or state.get('candidate_volume')!=red['volume']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or decision.get('manifest_sha256')!=state['manifest_sha256']
            or decision.get('action')!='reject_test_revision' or decision.get('optional_files')!=[]
            or not decision.get('findings') or not paths
            or any(type(reads.get(path,{}).get('lines')) is not int
                   or reads[path]['lines']<=0 or reads[path]['lines']!=reads[path].get('total_lines')
                   for path in paths)):
        raise ValueError('exact fully observed invalid citation required')
    result=json.loads(json.dumps(state))
    result['citation_recovery']=dict(failed_task=task['id'],invalid_decision=decision,
        prior_state=json.loads(json.dumps(state)),approval=False,author_restarted=False,attempt_limit=1)
    result.update(status='dispatch_intent')
    for key in ('wakeup_id','dispatched_at','reason','review_failure','read_evidence'):
        result.pop(key,None)
    return result


def prepare_typed_terminal_recovery(state, red, task, reviewer):
    """One new read-only review, not a recovered verdict or waived evidence."""
    if state.get('typed_terminal_recovery'):
        if state['typed_terminal_recovery']['failed_task']!=task['id']:
            raise ValueError('typed review recovery identity drift')
        return state
    failure=state.get('review_failure',{})
    if (state.get('status')!='blocked' or state.get('decision') or state.get('review_task')
            or state.get('terminal_contract')=='typed-review-v1'
            or failure.get('task_id')!=task['id']
            or failure.get('detail')!='independent test review did not complete'
            or task.get('status')!='failed' or task.get('agent_id')!=reviewer
            or task.get('wakeup_id')!=state.get('wakeup_id')
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or state.get('source_task')!=red['task_id']):
        raise ValueError('exact failed immutable review required')
    result=dict(state)
    result['typed_terminal_recovery']=dict(failed_task=task['id'],failed_wakeup=state['wakeup_id'],
        prior_failure=failure,manifest_sha256=state['manifest_sha256'],attempt_limit=1,
        delivery_approval=False,operation='readonly_typed_review_recovery_v1')
    for key in ('wakeup_id','marker','dispatched_at','review_failure','reason'):
        result.pop(key,None)
    result['status']='dispatch_intent'
    return result


def resume_typed_terminal(broker,payload):
    if not isinstance(payload,dict) or set(payload)!={'issue_id','failed_task','manifest_sha256','proxy_image'}:
        raise ValueError('exact typed review recovery required')
    try:import native
    except ImportError:from broker import native
    with broker.LOCK,broker.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle review recovery required')
        proxy=broker.docker('GET','/containers/'+broker.PREFIX+'-model-proxy-1/json')
        if (not re.fullmatch(r'sha256:[a-f0-9]{64}',payload['proxy_image']) or not proxy
                or proxy['Image']!=payload['proxy_image']
                or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=broker.PREFIX):
            raise ValueError('qualified installed review proxy required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(payload['issue_id'],)).fetchone())
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        if red['red']['manifest_sha256']!=payload['manifest_sha256']:raise ValueError('review snapshot drift')
        settings=json.loads((broker.STATE/'native.json').read_text())
        task=native.task_record(settings,payload['failed_task'],config['reviewer'])
        if task.get('issue_id')!=payload['issue_id']:raise ValueError('review issue drift')
        if any(r['status'] in ('queued','running') for r in native.issue_task_runs(settings,payload['issue_id'])):
            raise ValueError('idle native review required')
        updated=prepare_typed_terminal_recovery(state,red,task,config['reviewer'])
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',(json.dumps(updated,sort_keys=True),payload['issue_id']))
        return {'status':updated['status'],'failed_task':task['id'],'delivery_approval':False}


def prepare_observed_reconciliation(state,red,task,reads):
    """Re-evaluate the SAME verdict; never manufacture or reverse a decision."""
    if state.get('observed_reconciliation'):
        if state['observed_reconciliation']['task_id']!=task['id']:raise ValueError('reconciliation task drift')
        return state
    failure=state.get('review_failure',{})
    if (state.get('status')!='blocked' or state.get('decision') or state.get('review_task')
            or failure.get('detail')!='review requires observed artifact reads'
            or failure.get('task_id')!=task['id'] or task.get('status')!='completed'
            or task.get('wakeup_id')!=state.get('wakeup_id')
            or red['red']['manifest_sha256']!=state.get('manifest_sha256')
            or red['task_id']!=state.get('source_task')):
        raise ValueError('exact evidence-only blocked review required')
    paths={'/evidence/candidate/'+n for n in red['red']['test_sha256']}
    if not paths or not paths<=set(reads) or any(reads[p].get('lines',0)<=0 or reads[p].get('lines')!=reads[p].get('total_lines') for p in paths):
        raise ValueError('complete bound actual reads required')
    result=dict(state)
    result['observed_reconciliation']=dict(task_id=task['id'],manifest_sha256=state['manifest_sha256'],
        prior_failure=failure,prior_reason=state.get('reason'),read_receipt_sha256=hashlib.sha256(json.dumps(reads,sort_keys=True).encode()).hexdigest(),
        operation='same_review_transport_reconciliation_v1',delivery_approval=False)
    result['status']='awaiting_review'
    result.pop('review_failure',None);result.pop('reason',None)
    return result


def reconcile_observed_review(broker,issue,task_id):
    """Operator-only recovery after reader repair; no new native/model execution."""
    try:import native,handoff_runtime
    except ImportError:from broker import native,handoff_runtime
    with broker.LOCK,broker.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():raise ValueError('idle reconciliation required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone())
        if not config.get('initial_review'):raise ValueError('initial immutable review required')
        settings=json.loads((broker.STATE/'native.json').read_text())
        task=native.task_record(settings,task_id,config['reviewer'])
        if task.get('issue_id')!=issue:raise ValueError('native review issue drift')
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        reads=handoff_runtime.Effects(broker,settings).read_evidence(task)
        updated=prepare_observed_reconciliation(state,red,task,reads)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',(json.dumps(updated,sort_keys=True),issue))
        return {'status':updated['status'],'task_id':task_id,'model_calls_started':0,'delivery_approval':False}


def review_reason(config, parent_data):
    if config.get('source_harness_diagnosis'):
        if config['source_harness_diagnosis']!=parent_data.get('harness_diagnosis'):
            raise ValueError('source harness sponsorship drift')
        return ('Verify ALL sponsored NEW-harness repairs, not merely retained assertions. '
            'Check the DRIVER_BODY chronology, consume/create held responses, faithful POST body '
            'and current-before-stale request resolution. Require executable negative controls '
            'for query clearing and stale query/status painting. Unchanged driver or missing '
            'controls requires rejection. Structural admission is not semantic proof. '
            'Read complete snapshots and preserve every original assertion/method and baseline.')
    if config.get('negative_control_spike'):
        try:import incremental_negative_revision
        except ImportError:from broker import incremental_negative_revision
        proof=config['negative_control_spike'];incremental_negative_revision.validate_spike(proof,config['old_red'])
        if proof!=parent_data.get('negative_control_spike'):raise ValueError('spike review lineage drift')
        return ('CTO-sponsored helper-only NEW-test repair: read-only Node experiment isolates wrong quoted '
            'attribute capture groups in parseFragment and missing form containment in acceptsSearchInput. '
            'Inspect both immutable snapshots and the helper delta. Preserve all six historical methods and assertions. '
            'No baseline/product edits, weakened tests or fabricated reports. Experiment is not your approval; '
            'verify actual negative controls and original-base positive Red evidence independently.')
    if parent_data.get('harness_selector_experiment'):
        try:import incremental_harness_replan
        except ImportError:from broker import incremental_harness_replan
        proof=parent_data['harness_selector_experiment']
        completion=config.get('controls_completion')
        if completion:
            old=config['old_red']
            if (completion!=parent_data.get('controls_completion')
                    or proof!=config.get('harness_selector_experiment')
                    or parent_data.get('harness_fixture_volume')!=config.get('harness_fixture_volume')
                    or completion.get('task_id')!=old['task_id']
                    or completion.get('manifest_sha256')!=old['red']['manifest_sha256']
                    or completion.get('test_sha256')!=old['red']['test_sha256']):
                raise ValueError('controls completion review lineage drift')
            incremental_harness_replan.validate_experiment(proof,proof['input_sha256'])
        else:
            incremental_harness_replan.validate_experiment(proof,config['old_red']['red']['test_sha256'])
        if config['cto_decision']!=(parent_data.get('test_revision_proposal') or {}).get('decision_task'):
            raise ValueError('selector experiment sponsorship drift')
        if completion:
            return ('CTO-sponsored completion of missing negative controls. Current previous Red had '
                'two test methods/eight assertions but no additional negative-control methods. '
                'The earlier selector experiment is preserved as historical evidence, NOT claimed '
                'as execution against the current previous Red. Inspect both current snapshots; '
                'preserve every existing method/assertion and require genuine executable NEW methods '
                'for wrong input type, accessible label and inside-form placement, real source/Node '
                'execution, and no hardcoded reports, skips or product workaround. '
                'Controller admission checks do not constitute your independent approval.')
        return ('Controller-executed Node experiment confirms the previous fake DOM lacks attribute '
            'selectors, with and without CSS quotes. An unchanged copy is NOT a repair. Inspect actual '
            'querySelectorAll matching delta; preserve every historic method/assertion and baseline test. '
            'Require positive native search outside form and negative controls for wrong type, nonexistent '
            'type, inside-form placement and wrong accessible name. No product workaround for a mock defect. '
            'The experiment is NOT your review execution or delivery approval. Immutable experiment: '+
            json.dumps(proof['reports'],sort_keys=True,separators=(',',':')))
    if parent_data.get('assertion_replan'):
        try: import assertion_replan
        except ImportError: from broker import assertion_replan
        proof = assertion_replan.validated_record(parent_data)
        if config['cto_decision'] != parent_data['assertion_replan']['task']['id']:
            raise ValueError('replan review sponsor drift')
        return 'Controller-verified contradictions (not approval): ' + json.dumps(proof['contradictions'], ensure_ascii=False, separators=(',', ':'))
    if not parent_data.get('semantic_fixture_experiment'):
        return config['reason']
    try: import candidate_qualification
    except ImportError: from broker import candidate_qualification
    proof = parent_data['semantic_fixture_experiment']
    qualification = parent_data.get('candidate_qualification') or {}
    if (qualification.get('stage') != 'semantic_test_revision_qualified'
            or qualification.get('sponsor_task') != config['cto_decision']):
        raise ValueError('review sponsorship identity drift')
    candidate_qualification.validate_semantic_checks(qualification['review_decision'], proof)
    candidate_qualification.validate_semantic_checks(qualification['sponsor_decision'], proof)
    findings = candidate_qualification.validate_repair_findings(parent_data.get('semantic_repair_findings'),
        proof, config['old_red']['red']['test_sha256'])
    return ('Controller-verified NEW assertion contradictions (not delivery approval): '
            + json.dumps([[f['file'], f['query_line'], f['query'], f['title'],
                           f['asserted_match'], f['casefold_substring']] for f in findings],
                         ensure_ascii=False, separators=(',', ':'))
            + '. Fields: file,line,query,title,old asserted match,actual casefold match. '
            'Retain genuine nonmatch and accent-preserving Unicode coverage; inspect the actual revision.')


def semantic_scope(parent_data):
    """Only controller-recorded experiments activate this narrow check."""
    proof = parent_data.get('semantic_fixture_experiment') or parent_data.get('candidate_assertion_check')
    if not proof:
        return []
    scope = [{k: f[k] for k in ('file', 'test', 'title')} for f in proof['facts']]
    return list({json.dumps(f, sort_keys=True): f for f in scope}.values())


def validate_candidate_semantics(receipt, red, scope):
    import hashlib
    expected_scope = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    if (receipt.get('manifest_sha256') != red['red']['manifest_sha256']
            or receipt.get('scope_sha256') != expected_scope
            or receipt.get('operation') != 'python_str_strip_casefold_substring_v1'
            or receipt.get('fixture_literals_only') is not True
            or not receipt.get('facts')
            or not isinstance(receipt.get('contradictions'), list)
            or any(not any(all(f.get(k) == s[k] for k in ('file', 'test', 'title'))
                           for f in receipt['facts']) for s in scope)):
        raise ValueError('candidate semantic evidence identity mismatch')
    if receipt.get('contradictions'):
        raise ValueError('candidate assertions contradict recorded semantics')


def candidate_semantic_check(broker, red, scope):
    try: import failed_execution_evidence
    except ImportError: from broker import failed_execution_evidence
    import hashlib
    proof = failed_execution_evidence.capture(broker, red['task_id'], red['volume'],
        red['red']['test_sha256'], '', semantic=True, scope=scope)
    proof['scope_sha256'] = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    return proof


def revalidate_semantics(broker, payload):
    """Invalidate a disproved approval without rewriting its historical receipt.

    This operation does not retry a worker, grant test changes or approve a new
    release. The latest implementation incident remains the current handoff.
    """
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'manifest_sha256'}:
        raise ValueError('exact test review snapshot required')
    if str(uuid.UUID(payload['issue_id'])) != payload['issue_id'] or not re.fullmatch(r'[a-f0-9]{64}', payload['manifest_sha256']):
        raise ValueError('canonical test review identity required')
    try: import native, handoffs
    except ImportError: from broker import native, handoffs
    with broker.LOCK, broker.db() as con:
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                          (payload['issue_id'],)).fetchone()
        if not row:
            raise ValueError('test review missing')
        config, state = json.loads(row['config']), json.loads(row['state'])
        if state.get('manifest_sha256') != payload['manifest_sha256']:
            raise ValueError('test review snapshot drift')
        if state.get('semantic_revalidation'):
            return state['semantic_revalidation']
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (payload['issue_id'],)).fetchone()[0])
        settings = json.loads((broker.STATE / 'native.json').read_text())
        if (route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone()
                or any(r.get('status') in ('queued', 'running')
                       for r in native.issue_task_runs(settings, payload['issue_id']))):
            raise ValueError('paused idle semantic revalidation required')
        parent = con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (config.get('parent_issue'),)).fetchone()
        if not parent:
            raise ValueError('semantic parent missing')
        data = json.loads(parent[0])
        review_reason(config, data)  # validates independent sponsorship and old receipt
        scope = semantic_scope(data)
        if not scope:
            raise ValueError('controller-recorded semantic scope required')
        red = json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
                                     (payload['issue_id'],)).fetchone()[0])
        if red['red']['manifest_sha256'] != payload['manifest_sha256']:
            raise ValueError('Red snapshot drift')
        proof = candidate_semantic_check(broker, red, scope)
        if not proof['contradictions']:
            raise ValueError('no disproved assertion; approval not overridden')
        state['prior_approval'] = {k: state.get(k) for k in ('decision', 'review_task', 'reason')}
        receipt = {'request': payload, 'status': 'approval_invalidated_not_repaired',
                   'candidate_check': proof, 'at': time.time()}
        state.update(status='blocked', reason='candidate_semantic_contradiction',
                     semantic_candidate_check=proof, semantic_revalidation=receipt)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',
                    (json.dumps(state, sort_keys=True), payload['issue_id']))
        current = con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? '
                              'ORDER BY updated DESC LIMIT 1', (payload['issue_id'],)).fetchone()
        if not current or current['stage'] not in ('test_revision_required', 'technical_decision_required'):
            raise ValueError('current technical incident required')
        incident = json.loads(current['data'])
        incident.update(candidate_assertion_check=proof, invalidated_test_review=receipt,
                        required_action='source_bound_replan_of_all_contradictory_new_assertions')
        if incident.get('test_revision_proposal'):
            incident['prior_test_revision_proposal'] = incident.pop('test_revision_proposal')
        handoffs.save(con, current['source_task'], payload['issue_id'], 'technical_decision_required',
                      route['cto'], incident, time.time())
        return receipt


def register(broker, payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'parent_issue'}:
        raise ValueError('test revision requires explicit parent and child')
    for value in payload.values():
        if str(uuid.UUID(value)) != value:
            raise ValueError('canonical revision identity required')
    if payload['issue_id'] == payload['parent_issue']:
        raise ValueError('old issue cannot be overwritten')
    try:
        import remediation_runtime_guard
    except ImportError:
        from broker import remediation_runtime_guard
    if remediation_runtime_guard.lookup(broker, payload['parent_issue']) is not None:
        raise ValueError('remediation cannot reset original depth through a recursive child')
    with broker.LOCK, broker.db() as con:
        initialize(con)
        prior = con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',
                            (payload['issue_id'],)).fetchone()
        if prior:
            config = json.loads(prior[0])
            if config['parent_issue'] != payload['parent_issue']:
                raise ValueError('revision lineage drift')
            return config
        parent = con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (payload['parent_issue'],)).fetchone()
        if not parent or parent['stage'] != 'test_revision_required':
            raise ValueError('CTO-sponsored test revision required')
        data = json.loads(parent['data'])
        if data.get('source_harness_admission'):
            try:import source_harness_completion
            except ImportError:from broker import source_harness_completion
            parent_route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                (payload['parent_issue'],)).fetchone()[0])
            source_harness_completion.validate_diagnosis(data,parent_route)
            if (data.get('admission_recovery',{}).get('operation') not in ('cto_admission_recovery_v1','cto_controls_completion_v1')
                    or data['admission_recovery']['decision_task']!=data.get('test_revision_proposal',{}).get('decision_task')):
                raise ValueError('qualified admission recovery required')
        if data.get('assertion_replan'):
            try: import assertion_replan
            except ImportError: from broker import assertion_replan
            assertion_replan.validated_record(data)
        if data.get('semantic_fixture_experiment'):
            semantic = data.get('candidate_qualification') or {}
            if semantic.get('stage') != 'semantic_test_revision_qualified':
                raise ValueError('experiment-consistent independent sponsorship required')
            try: import candidate_qualification
            except ImportError: from broker import candidate_qualification
            candidate_qualification.validate_semantic_checks(semantic['review_decision'], data['semantic_fixture_experiment'])
            candidate_qualification.validate_semantic_checks(semantic['sponsor_decision'], data['semantic_fixture_experiment'])
            candidate_qualification.validate_repair_findings(data.get('semantic_repair_findings'),
                data['semantic_fixture_experiment'], (data.get('test_revision_proposal') or {}).get('new_test_files', []))
        proposal = data.get('test_revision_proposal') or {}
        parent_route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                               (payload['parent_issue'],)).fetchone()[0])
        child_route = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                  (payload['issue_id'],)).fetchone()
        if not child_route:
            raise ValueError('child delivery route missing')
        child = json.loads(child_route[0])
        if (not proposal.get('decision_task') or data.get('target') != parent_route['cto']
                or not child.get('test_first')
                or child['author'] != parent_route['author']
                or child['contract_sha256'] != parent_route['contract_sha256']
                or set(child['test_first_files']) != set(proposal.get('new_test_files', []))
                or len({child['techlead'], child['author'], parent_route['cto']}) != 3):
            raise ValueError('independent revision roles or proposal mismatch')
        old_base = broker.issue_base(payload['parent_issue'])
        new_base = broker.issue_base(payload['issue_id'])
        if old_base['base_sha'] != new_base['base_sha']:
            raise ValueError('test revision must use original Git base')
        old_red = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
                              (payload['parent_issue'],)).fetchone()
        if not old_red:
            raise ValueError('historic Red missing')
        historic = json.loads(old_red[0])
        if set(child['test_first_files']) != set(historic['red']['test_sha256']):
            raise ValueError('revision may only replace originally NEW tests')
        if con.execute('SELECT 1 FROM native_bindings WHERE issue_id=?',
                       (payload['issue_id'],)).fetchone():
            raise ValueError('revision registration must precede child execution')
        config = {**payload, 'reviewer': child['techlead'],
                  'cto_decision': proposal['decision_task'], 'base_sha': old_base['base_sha'],
                  'old_red': historic, 'reason': proposal['reason'], 'seed_previous_tests': True}
        if data.get('harness_diagnosis'):
            config['source_harness_diagnosis']=data['harness_diagnosis']
            config['seeded_edit_required']=True
            if data.get('admission_recovery',{}).get('operation')=='cto_controls_completion_v1':
                config['controls_completion_only']=True
                config['qualified_driver_sha256']=data['source_harness_admission']['proof']['candidate_driver_sha256']
        if data.get('harness_selector_experiment'):
            try:import incremental_harness_replan
            except ImportError:from broker import incremental_harness_replan
            if data.get('negative_control_spike'):
                try:import incremental_negative_revision
                except ImportError:from broker import incremental_negative_revision
                incremental_negative_revision.validate_spike(data['negative_control_spike'],historic)
                parent_trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(payload['parent_issue'],)).fetchone()[0])
                if parent_trial.get('harness_selector_experiment')!=data['harness_selector_experiment'] or parent_trial.get('harness_fixture_volume')!=data['harness_fixture_volume']:
                    raise ValueError('spike historical fixture drift')
                incremental_harness_replan.validate_experiment(data['harness_selector_experiment'],data['harness_selector_experiment']['input_sha256'])
                config['negative_control_spike']=data['negative_control_spike']
            elif data.get('controls_completion'):
                parent_trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',
                    (payload['parent_issue'],)).fetchone()[0])
                proof=data['controls_completion']
                if (parent_trial.get('harness_selector_experiment')!=data['harness_selector_experiment']
                        or parent_trial.get('harness_fixture_volume')!=data['harness_fixture_volume']
                        or proof.get('operation')!='immutable_candidate_missing_controls_diagnosis_v1'
                        or proof.get('task_id')!=historic['task_id']
                        or proof.get('manifest_sha256')!=historic['red']['manifest_sha256']
                        or proof.get('test_sha256')!=historic['red']['test_sha256']):
                    raise ValueError('historic experiment and current rejected seed lineage required')
                # Original selector experiment remains original; current rejected
                # tests become the seed. Never relabel original proof as a rerun.
                incremental_harness_replan.validate_experiment(data['harness_selector_experiment'],data['harness_selector_experiment']['input_sha256'])
                config['controls_completion']=proof
            else:
                incremental_harness_replan.validate_experiment(data['harness_selector_experiment'],historic['red']['test_sha256'])
            config.update(harness_selector_experiment=data['harness_selector_experiment'],
                          harness_fixture_volume=data['harness_fixture_volume'])
        con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',
                    (payload['issue_id'], payload['parent_issue'], json.dumps(config, sort_keys=True), '{}'))
        return config


def seed_source(broker, issue_id):
    """Select the prior Red only for newly registered, same-author revisions.

    Legacy executions are never retroactively reseeded. The source is mounted
    solely in the offline seed container, not in the author's worker.
    """
    try:
        import remediation_runtime_guard
    except ImportError:
        from broker import remediation_runtime_guard
    remediation_seed = remediation_runtime_guard.seed_source(broker, issue_id)
    if remediation_seed is not None:
        return remediation_seed
    try:
        import remediation_red_reference
    except ImportError:
        from broker import remediation_red_reference
    dependent_seed = remediation_red_reference.seed_source(broker, issue_id)
    if dependent_seed is not None:
        return dependent_seed
    with broker.db() as con:
        initialize(con)
        row = con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',
                          (issue_id,)).fetchone()
        if not row:
            return None
        config = json.loads(row['config'])
        if config.get('seed_previous_tests') is not True:
            return None
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (issue_id,)).fetchone()[0])
        parent = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                        (config['parent_issue'],)).fetchone()[0])
        prior_state=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',
                               (config['parent_issue'],)).fetchone()
        maintenance=config.get('maintenance_seed')
        if maintenance:
            try:import harness_repair_task
            except ImportError:from broker import harness_repair_task
            row=con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(maintenance['source'],)).fetchone()
            root,state=map(json.loads,row)
            receipt=maintenance['receipt'];facts=receipt['validation']
            correction=state.get('functional_correction')
            seed_valid=(receipt in state['staged']['history'] and receipt['checkpoint']==1)
            if correction and receipt==correction['seed'] and receipt['checkpoint']==2:
                report=state.get('functional_diagnosis_receipt',{})
                seed_valid=(correction.get('attempt_limit')==1 and correction.get('certificate')==report.get('certificate')
                    and report.get('classification')=='DRIVER_OBSERVATION'
                    and receipt['snapshot']==state['functional_diagnosis']['snapshot']
                    and receipt['validation']==state['functional_diagnosis']['validation'])
            if state.get('functional_fragment_recovery'):
                try:import maintenance_delivery
                except ImportError:from broker import maintenance_delivery
                seed_valid=(receipt==maintenance_delivery.fragment_seed(state))
            if state.get('c10_checkpoints'):
                try:import c10_checkpoint_contract as gates
                except ImportError:from broker import c10_checkpoint_contract as gates
                seed_valid=gates.admission(state).seed_binding(state,receipt)
            if (config.get('harness_maintenance_only') is not True or state['issue_id']!=issue_id
                    or route['enabled'] or route['author']!=root['author']
                    or config['base_sha']!=broker.issue_base(issue_id)['base_sha']
                    or not seed_valid
                    or not harness_repair_task.checkpoint_passed(facts)
                    or route['contract_sha256']!=parent['contract_sha256']
                    or set(route['test_first_files'])!={'tests/test_incremental_u3.py'}):
                raise ValueError('validated maintenance checkpoint required')
            snap=receipt['snapshot'];labels=broker.docker('GET','/volumes/'+snap['volume'])['Labels']
            if labels.get('delivery-kit.owner')!=broker.OWNER or labels.get('delivery-kit.source-task')!=receipt['task_id']:
                raise ValueError('maintenance checkpoint artifact identity mismatch')
            return {'mount':{'Type':'volume','Source':snap['volume'],'Target':'/previous','ReadOnly':True},
                'selection':{'manifest_sha256':facts['manifest_sha256'],'test_sha256':{'tests/test_incremental_u3.py':facts['test_sha256']}}}
    old = config['old_red']
    if (config['base_sha'] != broker.issue_base(issue_id)['base_sha']
            or route['author'] != parent['author']
            or route['contract_sha256'] != parent['contract_sha256']
            or set(route['test_first_files']) != set(old['red']['test_sha256'])):
        raise ValueError('revision seed lineage mismatch')
    actual = broker.docker('GET', '/volumes/' + old['volume'])
    labels = actual.get('Labels', {}) if actual else {}
    if (labels.get('delivery-kit.owner') != broker.OWNER
            or labels.get('delivery-kit.test-first-task') != old['task_id']):
        raise ValueError('revision seed artifact identity mismatch')
    selection={key:old['red'][key] for key in ('manifest_sha256','test_sha256')}
    invalidation=json.loads(prior_state[0]).get('size_invalidation') if prior_state else None
    if invalidation:
        request=invalidation['request']
        if (request['source_task']!=old['task_id']
                or request['manifest_sha256']!=old['red']['manifest_sha256']
                or invalidation['facts']['manifest_sha256']!=old['red']['manifest_sha256']):
            raise ValueError('historical size repair identity drift')
        selection['repair_input_bytes']=invalidation['oversized_test_bytes']
    return {'mount': {'Type': 'volume', 'Source': old['volume'],
                      'Target': '/previous', 'ReadOnly': True},
            'selection': selection}


def reconcile(broker, route, runs, effects, red):
    """True only after approval of the exact new Red by an independent profile."""
    try:
        import remediation_runtime_guard
    except ImportError:
        from broker import remediation_runtime_guard
    remediation_runtime_guard.require_historical_review(broker, route['issue_id'], route, red, effects)
    with broker.db() as con:
        initialize(con)
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                          (route['issue_id'],)).fetchone()
    if not row:
        # First submissions need the same independent gate as corrections.
        # NULL lineage means first submission, never a fabricated historic Red.
        if not route.get('techlead') or route['techlead'] == route['author']:
            raise ValueError('independent first-test reviewer required')
        if set(route['test_first_files']) != set(red['red']['test_sha256']):
            raise ValueError('first-test review scope drift')
        config = {'initial_review': True, 'reviewer': route['techlead'],
                  'base_sha': broker.issue_base(route['issue_id'])['base_sha'],
                  'reason': 'Review first NEW tests against the approved acceptance criteria.'}
        with broker.db() as con:
            con.execute('INSERT OR IGNORE INTO test_revision_trials VALUES (?,?,?,?)',
                        (route['issue_id'], None, json.dumps(config, sort_keys=True), '{}'))
            row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                              (route['issue_id'],)).fetchone()
    config, state = json.loads(row['config']), json.loads(row['state'])
    operative_reason = config['reason']
    scope = []
    if config.get('parent_issue'):
        with broker.db() as con:
            parent = con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=? '
                                 'ORDER BY updated DESC LIMIT 1', (config['parent_issue'],)).fetchone()
        if not parent:
            raise ValueError('revision parent evidence missing')
        parent_data = json.loads(parent[0])
        operative_reason = review_reason(config, parent_data)
        scope = semantic_scope(parent_data)
    if config['reviewer'] == route['author'] or config['reviewer'] != route['techlead']:
        raise ValueError('independent test reviewer identity drift')
    digest = red['red']['manifest_sha256']
    if state.get('manifest_sha256') not in (None, digest):
        raise ValueError('stale test revision approval or snapshot')
    if scope:
        try:
            if not state.get('semantic_candidate_check'):
                state['semantic_candidate_check'] = candidate_semantic_check(broker, red, scope)
                state.setdefault('source_task', red['task_id'])
                state.setdefault('manifest_sha256', digest)
                state.setdefault('status', 'semantic_validation_pending')
                _save(broker, route, state)
            validate_candidate_semantics(state['semantic_candidate_check'], red, scope)
        except ValueError as error:
            if state.get('status') == 'approved':
                state['prior_approval'] = {k: state.get(k) for k in ('decision', 'review_task', 'reason')}
            state.update(status='blocked', manifest_sha256=digest, source_task=red['task_id'],
                         reason='candidate_semantic_contradiction', semantic_failure=str(error))
            _save(broker, route, state)
            return False
    if state.get('status') == 'approved':
        if state.get('evidence_policy') and state.get('read_contract') != 'complete-lines-v2':
            paths = {'/evidence/' + tree + '/' + name
                     for tree in (('candidate',) if config.get('initial_review') else ('candidate', 'previous'))
                     for name in route['test_first_files']}
            reads = effects.read_evidence({'id': state['review_task']})
            missing = sorted(paths - set(reads))
            if missing:
                state['read_invalidation'] = {
                    'review_task': state['review_task'], 'decision': state.get('decision'),
                    'prior_read_evidence': state.get('read_evidence'), 'missing_paths': missing,
                    'reason': 'Numbered but clipped source lines are not complete inspection.'}
                state.update(status='blocked', reason='approved_review_has_incomplete_source_lines',
                             read_evidence={})
                _save(broker, route, state)
                return False
            state['read_contract'] = 'complete-lines-v2'
            _save(broker, route, state)
        return True
    if state.get('status') == 'blocked':
        if (not state.get('citation_recovery') and state.get('review_failure',{}).get('detail')
                == 'finding quote not observed at exact line'):
            failed=next((r for r in runs if r['id']==state['review_failure']['task_id']),None)
            if failed:
                paths=['/evidence/'+tree+'/'+name
                    for tree in (('candidate',) if config.get('initial_review') else ('candidate','previous'))
                    for name in route['test_first_files']]
                decision=effects.decision(failed)
                try:
                    validate_evidence(broker,route,state,decision)
                except ValueError as error:
                    if str(error)=='finding quote not observed at exact line':
                        state=prepare_citation_recovery(state,red,failed,config['reviewer'],decision,paths)
                        _save(broker,route,state)
                        return False
        if state.get('review_task') and state.get('read_evidence'):
            reconcile_rejection(broker, route, runs, effects, red, config, state)
        elif state.get('citation_recovery') and state.get('review_failure',{}).get('detail') in (
                'finding quote not observed at exact line','finding test or line does not exist',
                'finding line outside test'):
            failed=next((r for r in runs if r['id']==state['review_failure']['task_id']),None)
            paths=['/evidence/'+tree+'/'+name
                for tree in (('candidate',) if config.get('initial_review') else ('candidate','previous'))
                for name in route['test_first_files']]
            if (failed and failed['id']!=state['citation_recovery']['failed_task']
                    and failed.get('status')=='completed' and failed.get('agent_id')==config['reviewer']
                    and failed.get('wakeup_id')==state.get('wakeup_id')
                    and all(state.get('read_evidence',{}).get(p,{}).get('lines',0)>0
                        and state['read_evidence'][p]['lines']==state['read_evidence'][p].get('total_lines') for p in paths)):
                decision=effects.decision(failed)
                try:
                    validate_evidence(broker,route,state,decision)
                except ValueError as error:
                    if str(error)==state['review_failure']['detail']:
                        state.setdefault('protocol_diagnosis',dict(operation='invalid_review_citation_escalation_v1',
                            failed_task=failed['id'],invalid_decision=decision,
                            prior_failure=dict(state['review_failure']),approval=False,author_restarted=False))
                        reconcile_rejection(broker,route,runs,effects,red,config,state,protocol_task=failed['id'])
        return False
    if not state.get('evidence_policy') and hasattr(effects, 'test_review_report'):
        state['comparison'] = effects.test_review_report(route['issue_id'], red, config.get('old_red'))
        if config.get('remediation_run_id'):
            try:
                import remediation_test_review
            except ImportError:
                from broker import remediation_test_review
            remediation_test_review.validate_comparison(config, red, state['comparison'])
        state['evidence_policy'] = 1
    marker = hashlib.sha256((route['issue_id'] + ':' + red['task_id'] +
                             ':independent-test-revision:' + digest +
                             ':retry:' + str(state.get('bootstrap_retry', 0)) +
                             ':inspection:' + str(state.get('inspection_retry', 0)) +
                             ':pagination:' + str(state.get('pagination_retry', 0)) +
                             ':acp:' + str(state.get('acp_retry', 0)) +
                             (':storage:1' if state.get('storage_retry') else '') +
                             (':challenge:1' if state.get('challenge_retry') else '')+
                             (':typed-terminal:1' if state.get('typed_terminal_recovery') else '')+
                             (':format-repair:1' if state.get('format_recovery') else '')+
                             (':citation-repair:1' if state.get('citation_recovery') else '')).encode()).hexdigest()
    initial = config.get('initial_review', False)
    paths = ['/evidence/' + tree + '/' + name
             for tree in (('candidate',) if initial else ('candidate', 'previous'))
             for name in (red['red']['test_sha256'] if initial else config['old_red']['red']['test_sha256'])]
    instruction = (
        'CONTROLLER INDEPENDENT NEW-TEST REVISION REVIEW. Read only '
        '/evidence/candidate and /evidence/previous. Candidate is original Git '
        'base plus NEW tests, with controller-executed Red; it is not a product '
        'delivery. Revision basis: ' + operative_reason + '. Examine actual test '
        'files in both trees. Preserve behavioral coverage, all prior test '
        'methods/assertions, faithful DOM coercion, total=open+completed, '
        'real-source execution and deterministic flushing. Reject skips, '
        'weakened assertions, fabricated application logic, or a test incapable '
        'of Green on correct behavior. Do not edit any file or execute terminal '
        'commands. Product implementation is still blocked. Return ONLY JSON: '
        '{"action":"approve_test_revision" or "reject_test_revision",'
        '"reason":"specific evidence from the test", "optional_files":[], '
        '"manifest_sha256":"' + digest + '"}. This decision is NOT delivery approval.'
        '\nDELIVERY_STRUCTURED_DECISION_V1:test_review:' + digest + '\n')
    instruction += ''.join('DELIVERY_REVIEW_READ_PATH:' + path + '\n' for path in paths)
    if initial:
        instruction = (
            'CONTROLLER INDEPENDENT FIRST NEW-TEST REVIEW. Read only /evidence/candidate. '
            'This immutable snapshot contains the original Git base and NEW tests, '
            'not a product delivery. No previous revision exists. Evaluate coverage '
            'of the assigned acceptance criteria, faithful mocks, real-source execution '
            'and whether correct product behavior can attain Green. Reject skips, '
            'weakened assertions, fabricated application logic and unrealistic mock state. '
            'Inspect baseline code as needed. Do not write files or execute terminal commands. '
            'Implementation remains blocked. Return ONLY JSON: '
            '{"action":"approve_test_revision" or "reject_test_revision",'
            '"reason":"specific test evidence", "optional_files":[], '
            '"manifest_sha256":"' + digest + '"}. This is NOT delivery approval.\n'
            'DELIVERY_STRUCTURED_DECISION_V1:test_review:' + digest + '\n'
            + ''.join('DELIVERY_REVIEW_READ_PATH:' + path + '\n' for path in paths))
    if state.get('evidence_policy'):
        instruction = (
            'CONTROLLER INDEPENDENT NEW-TEST REVIEW. Inspect immutable candidate'
            + (' and previous tests' if not initial else ' tests (no previous revision exists)') +
            '. The candidate contains original Git base plus NEW tests and real controller Red, '
            'not a product delivery. Evaluate the approved issue criteria, faithful mocks, real-source '
            'execution and attainable Green. Preserve prior behavioral coverage; do not infer a '
            'regression from byte headroom or a historical unverified CTO claim. No terminal/writes. '
            'Return ONLY JSON: action (approve_test_revision/reject_test_revision), reason, '
            'optional_files=[], manifest_sha256=' + digest + ', findings. Approval permits '
            'implementation only, not delivery.\nDELIVERY_STRUCTURED_DECISION_V1:test_review:' + digest + '\n'
            + ''.join('DELIVERY_REVIEW_READ_PATH:' + path + '\n' for path in paths)
            + evidence_instruction(state))
    if config.get('remediation_run_id'):
        instruction = instruction.replace('Approval permits implementation only, not delivery.',
            'Approval completes the R1 test gate only; R1 stays tests-only. R2 requires separate controller authorization.')
    if scope:
        # This must follow the evidence-policy rewrite above; the old placement
        # was overwritten and never reached the reviewer.
        instruction += '\nSOURCE-BOUND REVISION BASIS: ' + operative_reason + '\n'
    instruction += ('\nDELIVERY_TYPED_REVIEW_V1:'+digest+'\n'
        'After all required reads, submit the actual verdict using submit_test_review. '
        'No prose/fences; no terminal or file edits. All findings and snapshot checks remain mandatory.\n')
    if state.get('citation_recovery'):
        instruction += ('\nThe previous review was INVALID because its quoted source did not match the exact '
            'numbered line. This is a fresh review of the SAME frozen tests, not permission to approve '
            'or change the tests. Read all pages again. Copy each quote verbatim from its actual line '
            'and verify the test symbol and line number. Independently judge behavioral coverage; '
            'source-string assertions are not evidence of real HTTP/browser behavior. '
            'Do not reuse an old verdict or invent a code location. One citation-format repair only.\n')
    if state.get('format_recovery'):
        instruction += ('\nFresh independent review after a rejected oversized submission. '
            'Read the same frozen evidence again and judge it independently. '
            'Keep reason <=1200 characters and finding quote/expected/observed <=500 each. '
            'The proxy permits one format-only correction, not a changed verdict or dropped findings. '
            'Previous failure was not approval; implementation remains blocked.\n')
    if 'wakeup_id' not in state:
        state.update(status='dispatch_intent', manifest_sha256=digest, terminal_contract='typed-review-v1',
                     source_task=red['task_id'], candidate_volume=red['volume'],
                     marker=marker)
        if not initial:
            state['previous_volume'] = config['old_red']['volume']
        _save(broker, route, state)
        wakeup = effects.ensure_wakeup(route['issue_id'], config['reviewer'], red['task_id'],
                                      marker, instruction,
                                      allow_create=effects.remaining_calls() >= route['minimum_calls'])
        if wakeup is None:
            return False
        state.update(wakeup_id=wakeup['id'], dispatched_at=time.time(), status='awaiting_review')
        _save(broker, route, state)
    candidates = [r for r in runs if r.get('wakeup_id') == state['wakeup_id']
                  and r.get('agent_id') == config['reviewer']]
    if len(candidates) > 1:
        raise ValueError('duplicate independent test review')
    if not candidates or candidates[0]['status'] in ('queued', 'dispatched', 'running'):
        if time.time() - state['dispatched_at'] > 1800:
            state.update(status='blocked', reason='independent_test_review_deadline')
            _save(broker, route, state)
        return False
    reviewer = candidates[0]
    try:
        if reviewer['status'] != 'completed':
            raise ValueError('independent test review did not complete')
        reads = effects.read_evidence(reviewer)
        if not set(paths) <= set(reads):
            raise ValueError('review requires observed artifact reads')
        state['read_evidence'] = {path: reads[path] for path in paths}
        decision = effects.decision(reviewer)
        if decision.get('manifest_sha256') != digest or decision.get('optional_files'):
            raise ValueError('test revision decision must match exact immutable snapshot')
        if decision['action'] not in ('approve_test_revision', 'reject_test_revision'):
            raise ValueError('explicit test revision review decision required')
        if state.get('evidence_policy'):
            validate_evidence(broker, route, state, decision)
        state.update(status='approved' if decision['action'] == 'approve_test_revision' else 'blocked',
                     review_task=reviewer['id'], reason=decision['reason'], decision=decision)
        if state['status'] == 'approved':
            state['read_contract'] = 'complete-lines-v2'
    except (ValueError, KeyError, TypeError) as error:
        state.update(status='blocked', reason='invalid_independent_test_review:' + type(error).__name__)
        state['review_failure'] = {'task_id': reviewer['id'], 'operation': 'review_evidence_validation',
                                   'error_type': type(error).__name__, 'detail': str(error)[:300]}
    _save(broker, route, state)
    if state['status'] == 'blocked' and state.get('review_task') and state.get('read_evidence'):
        reconcile_rejection(broker, route, runs, effects, red, config, state)
    return state['status'] == 'approved'


def reconcile_rejection(broker, route, runs, effects, red, config, state, protocol_task=None):
    """Preserve rejection; one CTO diagnosis can sponsor a NEW child, never approve."""
    cto = route['cto']
    if cto in (route['author'], config['reviewer']):
        raise ValueError('independent CTO required for rejected test review')
    diagnosis = state.setdefault('rejection_diagnosis', {})
    if diagnosis.get('status') in ('revision_required', 'blocked'):
        if (diagnosis.get('status')!='blocked' or not protocol_task or not state.get('protocol_diagnosis')
                or diagnosis.get('typed_transport_recovery')
                or diagnosis.get('failure',{}).get('operation')!='task_completion'
                or diagnosis.get('failure',{}).get('detail')!='CTO diagnosis did not complete'):
            return
        failed=next((r for r in runs if r['id']==diagnosis['failure']['task_id']),None)
        trees=('candidate',) if config.get('initial_review') else ('candidate','previous')
        required=['/evidence/'+tree+'/'+name for tree in trees for name in route['test_first_files']]
        reads=effects.read_evidence(failed) if failed else {}
        if (not failed or failed.get('status')!='failed' or failed.get('agent_id')!=cto
                or failed.get('wakeup_id')!=diagnosis.get('wakeup_id')
                or 'API call failed after 1 retries' not in str(failed.get('error',''))
                or any(reads.get(p,{}).get('lines',0)<=0
                    or reads[p]['lines']!=reads[p].get('total_lines') for p in required)):
            return
        prior=json.loads(json.dumps(diagnosis))
        diagnosis.clear();diagnosis.update(status='dispatch_intent',target=cto,
            typed_transport_recovery=dict(failed_task=failed['id'],prior_diagnosis=prior,
                attempt_limit=1,approval=False,author_restarted=False))
    trees = ('candidate',) if config.get('initial_review') else ('candidate', 'previous')
    paths = ['/evidence/' + tree + '/' + name
             for tree in trees for name in route['test_first_files']]
    if 'wakeup_id' not in diagnosis:
        source=protocol_task or state['review_task']
        marker = hashlib.sha256((route['issue_id'] + ':' + source +
                                 ':test-review-cto:' + state['manifest_sha256']+
                                 (':typed-transport:1' if diagnosis.get('typed_transport_recovery') else '')).encode()).hexdigest()
        instruction = (
            ('CONTROLLER INVALID REVIEW PROTOCOL. Two reviews cited invalid locations. '
             'Neither verdict was accepted; do not treat either as a valid rejection. '
             'Independently inspect actual frozen test coverage against the issue criteria. '
             'You may sponsor NEW tests only with your own concrete observed finding; '
             'you cannot approve or override the invalid review. Implementation stays blocked. '
             'Protocol failure: '+state['review_failure']['detail']+'. '
             if protocol_task else
            'CONTROLLER REJECTED NEW-TEST REVIEW. Inspect the immutable tests; '
            'the review rejection remains valid and implementation stays blocked. '
            'Review finding (a claim to assess, not unquestionable truth): ' + state['reason'] + '. ')+
            'Original product criteria remain in the issue brief. Diagnose whether '
            'the harness faithfully tests them; distinguish unit listener invocation '
            'from real browser dispatch and disabled-button semantics. Do not weaken '
            'coverage or claim a browser result. Return ONLY JSON: action '
            '(request_test_revision or escalate_cto), reason (1 to 1200 characters: '
            'one concrete finding and correction for the original author; no essay), '
            'optional_files ([]). Compare candidate and previous when both exist; '
            'claims of lost coverage require actual inspection of the previous tests. '
            'Distinguish pre-submit observations from pending observations: never '
            'require opposite values of the same frozen observation. '
            'request_test_revision sponsors a NEW child on the original Git base; '
            'it does not edit or approve this snapshot. No terminal or writes.\n'
            'DELIVERY_STRUCTURED_DECISION_V1:technical\n' +
            ''.join('DELIVERY_REVIEW_READ_PATH:' + path + '\n' for path in paths))
        if state.get('evidence_policy'):
            instruction += evidence_instruction(state)
            instruction += '\nDELIVERY_TYPED_DECISION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\n'
        diagnosis.update(status='dispatch_intent', marker=marker, target=cto)
        _save_rejection(broker, route, state)
        wakeup = effects.ensure_wakeup(route['issue_id'], cto, source,
                                      marker, instruction,
                                      allow_create=effects.remaining_calls() >= route['minimum_calls'])
        if wakeup is None:
            return
        diagnosis.update(status='awaiting_cto', wakeup_id=wakeup['id'], dispatched_at=time.time())
        _save_rejection(broker, route, state)
    candidates = [r for r in runs if r.get('agent_id') == cto and
                  r.get('wakeup_id') == diagnosis['wakeup_id']]
    if len(candidates) > 1:
        diagnosis.update(status='blocked', reason='duplicate_cto_test_review_diagnosis')
    elif not candidates or candidates[0]['status'] in ('queued', 'dispatched', 'running'):
        if time.time() - diagnosis['dispatched_at'] <= 1800:
            return
        diagnosis.update(status='blocked', reason='cto_test_review_deadline')
    else:
        task = candidates[0]
        failure = {'task_id': task['id'], 'operation': 'task_completion',
                   'next_action': 'technical_replan', 'reason_max_length': 1200}
        try:
            if task['status'] != 'completed':
                raise ValueError('CTO diagnosis did not complete')
            failure['operation'] = 'artifact_reads'
            reads = effects.read_evidence(task)
            if not set(paths) <= set(reads):
                raise ValueError('CTO diagnosis requires observed artifact reads')
            failure['operation'] = 'structured_decision'
            decision = effects.decision(task)
            if isinstance(decision.get('reason'), str):
                failure['reason_length'] = len(decision['reason'])
            if (decision.get('action') != 'request_test_revision' or decision.get('optional_files') != []
                    or not isinstance(decision.get('reason'), str) or not 0 < len(decision['reason']) <= 1200):
                raise ValueError('CTO requires technical replan, not approval override')
            if state.get('evidence_policy'):
                validate_evidence(broker, route, state, decision)
            diagnosis.update(status='revision_required', decision_task=task['id'],
                             decision=decision, read_evidence={p: reads[p] for p in paths})
        except (ValueError, KeyError, TypeError) as error:
            diagnosis.update(status='blocked', reason='invalid_cto_test_review_diagnosis:' + type(error).__name__,
                             failure={**failure, 'error_type': type(error).__name__, 'detail': str(error)[:300]})
    _save_rejection(broker, route, state)


def evidence_instruction(state):
    compact = {path: {'method_counts': [len(f['previous_methods']), len(f['candidate_methods'])],
                      'assertion_counts': [f['previous_assertions'], f['candidate_assertions']],
                      'removed_methods': f['removed_methods'], 'added_methods': f['added_methods'],
                      'assertion_ast_changed_method_count': len(f['removed_assertion_ast'])}
               for path, f in state['comparison']['files'].items()}
    summary = json.dumps(compact, separators=(',', ':'))
    if len(summary) > 1200:
        # Names scale with test coverage. Keep the full immutable comparison in
        # controller state; the prompt is only an index, not semantic evidence.
        facts = list(state['comparison']['files'].values())
        summary = json.dumps({
            'summary_only': True,
            'comparison_sha256': hashlib.sha256(json.dumps(state['comparison'],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'file_count': len(facts),
            'method_counts': [sum(len(f['previous_methods']) for f in facts),
                              sum(len(f['candidate_methods']) for f in facts)],
            'assertion_counts': [sum(f['previous_assertions'] for f in facts),
                                 sum(f['candidate_assertions'] for f in facts)],
            'removed_method_count': sum(len(f['removed_methods']) for f in facts),
            'added_method_count': sum(len(f['added_methods']) for f in facts),
            'assertion_ast_changed_method_count': sum(len(f['removed_assertion_ast']) for f in facts)
        }, separators=(',', ':'))
    return ('\nDELIVERY_TEST_FINDINGS_V1\nDELIVERY_OBSERVED_FINDINGS_V1\nController structural facts (method-scoped assertions, not semantic approval): ' + summary +
            '\nA summary-only index omits names, not evidence: read all declared immutable test paths. '
            'Counts or digest alone cannot justify approval or rejection. '
            'Include findings: [] for approval; 1-3 concrete findings for rejection/revision. Each has '
            'kind (removed_method,removed_assertion,semantic_regression,missing_coverage,invalid_harness), '
            'tree (candidate/previous), path (repository-relative), test (Class.test_method or __module__), '
            'line (integer), quote (observed substring at that line), expected, observed. '
            'Quotes/expected/observed <=500 characters. Removed-method claims must match the actual diff. '
            'Byte headroom alone is not a defect. Historical CTO claims are hypotheses, not facts. '
            'AST changes can be assertion diagnostic-message changes, not assertion removal. '
            'Do not invent methods or assertions. Missing semantic coverage still requires a concrete observed location.\n')


def validate_evidence(broker, route, state, decision):
    try:
        import test_review_report, test_review_facts
    except ImportError:
        from broker import test_review_report, test_review_facts
    report = test_review_report.load(broker, route['issue_id'], state['manifest_sha256'])
    if report['summary'] != state['comparison']:
        raise ValueError('comparison evidence identity drift')
    test_review_facts.validate_findings(decision, report)
    try:
        import remediation_runtime_guard, remediation_test_review
    except ImportError:
        from broker import remediation_runtime_guard, remediation_test_review
    if remediation_runtime_guard.lookup(broker, route['issue_id']) is not None:
        remediation_test_review.preserve_coverage(decision, report['summary'])


def _save_rejection(broker, route, state):
    try:
        import handoffs
    except ImportError:
        from broker import handoffs
    diagnosis = state['rejection_diagnosis']
    stage = ('test_revision_required' if diagnosis['status'] == 'revision_required' else
             'test_revision_blocked' if diagnosis['status'] == 'blocked' else 'test_review_cto_diagnosis')
    data = {**state, 'target': route['cto']}
    if diagnosis['status'] == 'revision_required':
        data['decision'] = diagnosis['decision']
        data['test_revision_proposal'] = {'decision_task': diagnosis['decision_task'],
            'source_task': state['source_task'], 'new_test_files': route['test_first_files'],
            'reason': diagnosis['decision']['reason']}
    if diagnosis['status'] == 'blocked':
        data['reason'] = diagnosis['reason']
    with broker.db() as con:
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',
                    (json.dumps(state, sort_keys=True), route['issue_id']))
        handoffs.save(con, state['source_task'], route['issue_id'], stage, route['cto'], data, time.time())


def resume_inspection(broker, payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'review_task', 'manifest_sha256'}:
        raise ValueError('exact uninspected decision identity required')
    try:
        import native, handoffs
    except ImportError:
        from broker import native, handoffs
    with broker.LOCK, broker.db() as con:
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?', (payload['issue_id'],)).fetchone()
        if not row:
            raise ValueError('test revision trial missing')
        config, state = json.loads(row['config']), json.loads(row['state'])
        if state.get('manifest_sha256') != payload['manifest_sha256']:
            raise ValueError('inspection snapshot identity drift')
        if state.get('uninspected_task') == payload['review_task']:
            return {'resumed': True}
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (payload['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
            raise ValueError('inspection repair requires paused idle route')
        if state.get('status') != 'blocked' or state.get('inspection_retry') or state.get('review_task') != payload['review_task']:
            raise ValueError('only one uninspected decision may resume')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        task = next((r for r in runs if r['id'] == payload['review_task']), None)
        if not task or task.get('status') != 'completed' or task.get('agent_id') != config['reviewer'] or task.get('wakeup_id') != state.get('wakeup_id') or any(r.get('status') in ('queued', 'running') for r in runs):
            raise ValueError('exact completed independent reviewer required')
        messages = native.task_messages(settings, task['id'])
        if any(m.get('type') == 'tool_use' and m.get('tool') == 'read_file' for m in messages):
            raise ValueError('a reviewed rejection cannot be overridden')
        state.update(inspection_retry=1, uninspected_task=task['id'], uninspected_reason=state.get('reason'), status='dispatch_intent')
        for field in ('wakeup_id', 'dispatched_at', 'reason', 'review_task'):
            state.pop(field, None)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?', (json.dumps(state, sort_keys=True), payload['issue_id']))
        handoffs.save(con, state['source_task'], payload['issue_id'], 'awaiting_test_revision_review', config['reviewer'], state, time.time())
        return {'resumed': True}


def resume_pagination(broker, payload, *, acp_repair=False, storage_repair=False):
    """One repair of the proven read loop, never an override of a verdict."""
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'failed_task', 'manifest_sha256'}:
        raise ValueError('exact pagination recovery identity required')
    try:
        import native, handoffs
    except ImportError:
        from broker import native, handoffs
    if acp_repair and storage_repair:raise ValueError('one inspection recovery class required')
    prefix = 'storage' if storage_repair else 'acp' if acp_repair else 'pagination'
    with broker.LOCK, broker.db() as con:
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                          (payload['issue_id'],)).fetchone()
        if not row:
            raise ValueError('test revision trial missing')
        config, state = json.loads(row['config']), json.loads(row['state'])
        if state.get('manifest_sha256') != payload['manifest_sha256']:
            raise ValueError('pagination snapshot identity drift')
        if state.get(prefix + '_failed_task') == payload['failed_task']:
            return {'resumed': True, 'issue_id': payload['issue_id']}
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (payload['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
            raise ValueError('pagination repair requires paused idle route')
        if (state.get('status') != 'blocked' or state.get(prefix + '_retry')
                or (acp_repair and state.get('pagination_retry') != 1)
                or state.get('review_task') or state.get('read_evidence')
                or state.get('reason') != 'invalid_independent_test_review:ValueError'):
            raise ValueError('only one proven inspection infrastructure failure may resume')
        receipt = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
                              (payload['issue_id'],)).fetchone()
        red = json.loads(receipt[0]) if receipt else {}
        if (red.get('task_id') != state.get('source_task')
                or red.get('volume') != state.get('candidate_volume')
                or red.get('red', {}).get('manifest_sha256') != payload['manifest_sha256']):
            raise ValueError('frozen Red identity drift')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        task = next((r for r in runs if r['id'] == payload['failed_task']), None)
        if (not task or task.get('status') != 'completed' or task.get('agent_id') != config['reviewer']
                or task.get('wakeup_id') != state.get('wakeup_id')
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('exact terminal independent reviewer required')
        output = (task.get('result') or {}).get('output', '')
        expected_failure = (r'HTTP 400: \{"error":\{"code":"review_inspection_stalled"\}\}' if acp_repair
                            else r'Context length exceeded \([\d,]+ tokens\)\. Cannot compress further\.')
        if not storage_repair and (not isinstance(output, str) or not re.fullmatch(expected_failure, output.strip())):
            raise ValueError('recorded read-loop context failure required; verdicts cannot be overridden')
        messages = native.task_messages(settings, task['id'])
        def stalled_read(message):
            if message.get('type') != 'tool_result' or not isinstance(message.get('output'), str):
                return False
            if not acp_repair:
                return message['output'].startswith('Read failed: BLOCKED: You have called read_file')
            try:
                data = json.loads(message['output'])
            except ValueError:
                return False
            return (isinstance(data, dict) and data.get('dedup') is True
                    and data.get('content_returned') is False and data.get('status') == 'unchanged')
        if storage_repair:
            paths={'/evidence/'+tree+'/'+name for tree in ('candidate','previous')
                   for name in route['test_first_files']}
            if (paths<=set(observations(messages)) or not any(m.get('type')=='tool_result'
                    and m.get('tool')=='read_file' and m.get('output_truncated') is True for m in messages)):
                raise ValueError('incomplete native read with recorded truncation required')
        elif observations(messages) or not any(stalled_read(m) for m in messages):
            raise ValueError('uninspected read-loop evidence required')
        state.update(status='dispatch_intent')
        state[prefix + '_retry'] = 1
        state[prefix + '_failed_task'] = task['id']
        state[prefix + '_incident'] = {'reason': state['reason'], 'terminal_output': output,
            'messages_sha256': hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()}
        for field in ('wakeup_id', 'dispatched_at', 'reason'):
            state.pop(field, None)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',
                    (json.dumps(state, sort_keys=True), payload['issue_id']))
        handoffs.save(con, state['source_task'], payload['issue_id'], 'awaiting_test_revision_review',
                      config['reviewer'], state, time.time())
        return {'resumed': True, 'issue_id': payload['issue_id']}


def resume_bootstrap(broker, payload):
    """One fixed maintenance retry of failed initialization, never a verdict."""
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'failed_task', 'manifest_sha256'}:
        raise ValueError('exact bootstrap recovery identity required')
    try:
        import native, handoffs
    except ImportError:
        from broker import native, handoffs
    with broker.LOCK, broker.db() as con:
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                          (payload['issue_id'],)).fetchone()
        if not row:
            raise ValueError('test revision trial missing')
        config, state = json.loads(row['config']), json.loads(row['state'])
        if state.get('manifest_sha256') != payload['manifest_sha256']:
            raise ValueError('bootstrap snapshot identity drift')
        if state.get('bootstrap_failed_task') == payload['failed_task']:
            return {'resumed': True, 'issue_id': payload['issue_id']}
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                        (payload['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
            raise ValueError('bootstrap recovery requires paused idle route')
        if state.get('status') != 'blocked' or state.get('bootstrap_retry'):
            raise ValueError('only one failed bootstrap may resume')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        task = next((r for r in runs if r['id'] == payload['failed_task']), None)
        if (not task or task.get('status') != 'failed' or task.get('agent_id') != config['reviewer']
                or task.get('wakeup_id') != state.get('wakeup_id')
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('exact failed independent reviewer required')
        error = con.execute('SELECT 1 FROM broker_errors e JOIN native_bindings n USING(request_id) '
                            'WHERE n.task_id=? AND e.operation=? AND e.category=?',
                            (payload['failed_task'], 'transport_start', 'bootstrap:broker_internal')).fetchone()
        if not error:
            try:
                import review_dependency_recovery
            except ImportError:
                from broker import review_dependency_recovery
            repaired=review_dependency_recovery.repaired(broker,con,payload,task,state)
            if not repaired:
                raise ValueError('recorded bootstrap incident missing')
            state['dependency_recovery']=repaired
        state.update(status='dispatch_intent', bootstrap_retry=1, bootstrap_failed_task=payload['failed_task'])
        for field in ('wakeup_id', 'dispatched_at', 'reason'):
            state.pop(field, None)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',
                    (json.dumps(state, sort_keys=True), payload['issue_id']))
        handoffs.save(con, state['source_task'], payload['issue_id'], 'awaiting_test_revision_review',
                      config['reviewer'], state, time.time())
        return {'resumed': True, 'issue_id': payload['issue_id']}


def _save(broker, route, state):
    try:
        import handoffs
    except ImportError:
        from broker import handoffs
    with broker.db() as con:
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',
                    (json.dumps(state, sort_keys=True), route['issue_id']))
        handoffs.save(con, state['source_task'], route['issue_id'],
                      'test_revision_approved' if state['status'] == 'approved' else
                      'test_revision_blocked' if state['status'] == 'blocked' else 'awaiting_test_revision_review',
                      route['techlead'], state, time.time())


def planning_mounts(broker, request_id):
    """Only controller-selected immutable artifacts, never agent-provided paths."""
    with broker.db() as con:
        initialize(con)
        binding = con.execute('SELECT issue_id,agent_id FROM native_bindings WHERE request_id=?',
                              (request_id,)).fetchone()
        if not binding:
            return []
        try:import calibration_failure_plan
        except ImportError:from broker import calibration_failure_plan
        diagnosis=calibration_failure_plan.mounts(broker,{**dict(binding),'request_id':request_id})
        if diagnosis:return diagnosis
        try:import calibration_rework
        except ImportError:from broker import calibration_rework
        rework=calibration_rework.mounts(broker,{**dict(binding),'request_id':request_id})
        if rework:return rework
        try: import technical_remediation_plan
        except ImportError: from broker import technical_remediation_plan
        remediation = technical_remediation_plan.mounts(broker, dict(binding))
        if remediation:
            return remediation
        try:import u3_coverage_integration
        except ImportError:from broker import u3_coverage_integration
        integration=u3_coverage_integration.mounts(broker,{**dict(binding),'request_id':request_id})
        if integration:return integration
        try:import u3_product_intake
        except ImportError:from broker import u3_product_intake
        coverage=u3_product_intake.mounts(broker,{**dict(binding),'request_id':request_id})
        if coverage:return coverage
        try:import u3_controls_execution
        except ImportError:from broker import u3_controls_execution
        controls=u3_controls_execution.mounts(broker,{**dict(binding),'request_id':request_id})
        if controls:return controls
        try:import maintenance_delivery
        except ImportError:from broker import maintenance_delivery
        maintenance=maintenance_delivery.mounts(broker,{**dict(binding),'request_id':request_id})
        if maintenance:return maintenance
        try: import adapted_test_review
        except ImportError: from broker import adapted_test_review
        adapted = adapted_test_review.mounts(broker, {**dict(binding), 'request_id': request_id})
        if adapted:
            return adapted
        try: import harness_prerequisite
        except ImportError: from broker import harness_prerequisite
        prerequisite=harness_prerequisite.mounts(broker,{**dict(binding),'request_id':request_id})
        if prerequisite:
            return prerequisite
        try: import harness_repair_task
        except ImportError: from broker import harness_repair_task
        repair=harness_repair_task.mounts(broker,{**dict(binding),'request_id':request_id})
        if repair:
            return repair
        try: import test_decomposition
        except ImportError: from broker import test_decomposition
        decomposition = test_decomposition.mounts(broker,{**dict(binding),'request_id':request_id})
        if decomposition:
            return decomposition
        try: import assertion_replan
        except ImportError: from broker import assertion_replan
        replan = assertion_replan.mounts(broker, {**dict(binding), 'request_id': request_id})
        if replan:
            return replan
        try: import candidate_qualification
        except ImportError: from broker import candidate_qualification
        qualification = candidate_qualification.mounts(broker, {**dict(binding), 'request_id': request_id})
        if qualification:
            return qualification
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                          (binding['issue_id'],)).fetchone()
    if not row:
        return diagnostic_mounts(broker, binding)
    config, state = json.loads(row['config']), json.loads(row['state'])
    diagnosis = state.get('rejection_diagnosis', {})
    cto_inspection = (diagnosis.get('target') == binding['agent_id'] and
                      diagnosis.get('status') in ('dispatch_intent', 'awaiting_cto'))
    if not cto_inspection and (config['reviewer'] != binding['agent_id'] or state.get('status') not in ('dispatch_intent', 'awaiting_review')):
        # A completed test review is historical state, not the current purpose
        # of a planning execution. It must not shadow a later frozen-suite
        # diagnosis for the same issue. diagnostic_mounts rechecks recipient,
        # snapshot identity and read-only volume labels independently.
        return diagnostic_mounts(broker, binding)
    mounts = []
    artifacts = [('/evidence/candidate', state['candidate_volume'], state['source_task'])]
    if not config.get('initial_review'):
        artifacts.append(('/evidence/previous', state['previous_volume'], config['old_red']['task_id']))
    for target, volume, source in artifacts:
        actual = broker.docker('GET', '/volumes/' + volume)
        labels = actual.get('Labels', {}) if actual else {}
        if labels.get('delivery-kit.owner') != broker.OWNER or labels.get('delivery-kit.test-first-task') != source:
            raise ValueError('test revision artifact identity mismatch')
        mounts.append({'Type': 'volume', 'Source': volume, 'Target': target, 'ReadOnly': True})
    return mounts


def diagnostic_mounts(broker, binding):
    """Technical diagnosis sees failed code/tests, not only their names."""
    with broker.db() as con:
        row = con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=? '
                          'ORDER BY updated DESC LIMIT 1', (binding['issue_id'],)).fetchone()
        if not row:
            return []
        data = json.loads(row[0])
        if data.get('structural_diagnosis'):
            try:import structural_diagnosis
            except ImportError:from broker import structural_diagnosis
            return structural_diagnosis.mounts(broker,data,binding)
        failure = data.get('validation_failure') or {}
        if data.get('target') != binding['agent_id'] or not data.get('artifact_diagnosis'):
            return []
        source = con.execute('SELECT volume FROM snapshots WHERE task_id=? AND status=?',
                             (failure.get('source_task'), 'complete')).fetchone()
        diagnostic = data.get('failed_execution_diagnostic')
        lost = data.get('lost_execution_diagnostic')
        if lost:
            recorded = con.execute('SELECT receipt FROM lost_execution_diagnoses WHERE source_task=?',
                                   (failure.get('source_task'),)).fetchone()
            if (not recorded or json.loads(recorded[0]) != lost or lost['failure'] != failure
                    or lost.get('delivery_approval') is not False):
                raise ValueError('lost diagnostic receipt mismatch')
            source = (lost['volume'],)
        if diagnostic:
            recorded = con.execute('SELECT receipt FROM failed_execution_diagnoses WHERE source_task=?',
                                   (failure.get('source_task'),)).fetchone()
            if (not recorded or json.loads(recorded[0]) != diagnostic
                    or diagnostic['failure'] != failure):
                raise ValueError('failed diagnostic receipt mismatch')
            source = con.execute('SELECT volume FROM failed_execution_snapshots WHERE task_id=? AND status=?',
                                 (failure.get('source_task'), 'complete')).fetchone()
        red = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
                          (binding['issue_id'],)).fetchone()
    if red is None:
        try:import remediation_red_reference
        except ImportError:from broker import remediation_red_reference
        reference=remediation_red_reference.qualified(broker,binding['issue_id'])
        red=(json.dumps(reference['red']),) if reference is not None else None
    if not source or not red or source[0] != failure.get('volume'):
        raise ValueError('diagnostic immutable artifacts missing')
    old = json.loads(red[0])
    mounts = []
    for target, volume, label, task in (
        ('/evidence/candidate', source[0], 'delivery-kit.source-task', failure['source_task']),
        ('/evidence/previous', old['volume'], 'delivery-kit.test-first-task', old['task_id'])):
        actual = broker.docker('GET', '/volumes/' + volume)
        labels = actual.get('Labels', {}) if actual else {}
        if labels.get('delivery-kit.owner') != broker.OWNER or labels.get(label) != task:
            raise ValueError('diagnostic artifact identity mismatch')
        if (diagnostic or lost) and target == '/evidence/candidate' and labels.get('delivery-kit.diagnostic-only') != 'true':
            raise ValueError('failed diagnostic volume identity mismatch')
        mounts.append({'Type': 'volume', 'Source': volume, 'Target': target, 'ReadOnly': True})
    return mounts
