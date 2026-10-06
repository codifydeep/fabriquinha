"""Controller-internal unit binding and durable, idempotent author dispatch.

Not wired into the production supervisor until initial-base validation and
per-unit evidence reconciliation are qualified. No worker-facing endpoints.
"""
import json
import time
try:
    import incremental_checkpoints as ledger
    import incremental_evidence as evidence
except ImportError:
    from broker import incremental_checkpoints as ledger, incremental_evidence as evidence


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS incremental_unit_owners('
        'issue_id TEXT PRIMARY KEY,source_task TEXT,unit TEXT,revision INTEGER)')
    con.execute('CREATE TABLE IF NOT EXISTS incremental_dispatch_intents('
        'source_task TEXT,unit TEXT,revision INTEGER,marker TEXT UNIQUE,state TEXT,'
        'PRIMARY KEY(source_task,unit,revision))')


def bind(con,source,unit_id,issue_id,receipt,prior_suite):
    """Register an already controller-materialized base; never create a workspace."""
    initialize(con)
    with ledger._atomic(con):
        row=con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone()
        if not row:raise ValueError('checkpoint contract missing')
        config,state=map(json.loads,row);unit=state['units'].get(unit_id)
        if not unit or unit['stage']!='awaiting_red':raise ValueError('unit not ready for binding')
        expected={'checkpoint_manifest_sha256','base_manifest_sha256','contract_sha256','base_sha',
                  'baseline_test_sha256','new_test','suite_sha256'}
        if (set(receipt)!=expected or receipt['checkpoint_manifest_sha256']!=unit['base_manifest_sha256']
                or receipt['baseline_test_sha256']!=unit['baseline_test_sha256']
                or receipt['suite_sha256']!=config['policy']['suite_sha256']):
            raise ValueError('controller materialization lineage mismatch')
        for key in ('checkpoint_manifest_sha256','base_manifest_sha256','contract_sha256','suite_sha256'):
            ledger._hash(receipt[key])
        base=con.execute('SELECT base_sha,manifest_sha256 FROM issue_bases WHERE issue_id=?',(issue_id,)).fetchone()
        route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue_id,)).fetchone()
        if not route or not base or tuple(base)!=(receipt['base_sha'],receipt['base_manifest_sha256']):
            raise ValueError('exact installed child base required')
        route=json.loads(route[0]);policy=config['policy']
        if (route['enabled'] or not route.get('test_first')
                or route['test_first_files']!=[receipt['new_test']]
                or route['author']!=policy['author'] or route['techlead']!=policy['test_reviewer']
                or route['reviewer']!=policy['delivery_reviewer']
                or route['contract_sha256']!=receipt['contract_sha256']
                or issue_id==config['issue_id']):
            raise ValueError('paused fresh independently reviewed unit route required')
        evidence._prior_suite(con,prior_suite,config,unit)
        binding=dict(issue_id=issue_id,materialization=receipt,prior_suite=prior_suite)
        if unit.get('binding'):
            if unit['binding']!=binding:raise ValueError('unit binding immutable')
            return state
        if con.execute('SELECT 1 FROM native_bindings WHERE issue_id=?',(issue_id,)).fetchone():
            raise ValueError('unit binding must precede execution')
        unit['binding']=binding
        unit['materialized_base_manifest_sha256']=receipt['base_manifest_sha256']
        owner=con.execute('SELECT source_task,unit,revision FROM incremental_unit_owners WHERE issue_id=?',(issue_id,)).fetchone()
        if owner and tuple(owner)!=(source,unit_id,unit['revision']):raise ValueError('unit issue ownership conflict')
        con.execute('INSERT OR IGNORE INTO incremental_unit_owners VALUES(?,?,?,?)',(issue_id,source,unit_id,unit['revision']))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return state


def owns(con,issue_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='incremental_unit_owners'").fetchone():return False
    return con.execute('SELECT 1 FROM incremental_unit_owners WHERE issue_id=?',(issue_id,)).fetchone() is not None


def dispatch(con,source,unit_id,effects,*,now=None):
    """Persist intent before remote wakeup; lookup by stable marker after restart.

    Effects must be the real controller Effects adapter. It provides the durable
    native ensure_wakeup lookup and current capacity/budget, never agent claims.
    """
    initialize(con);now=time.time() if now is None else now
    row=con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone()
    if not row:raise ValueError('checkpoint contract missing')
    config,state=map(json.loads,row);unit=state['units'].get(unit_id)
    if not unit or unit['stage']!='awaiting_red' or not unit.get('binding'):
        raise ValueError('verified unit binding required before dispatch')
    issue=unit['binding']['issue_id']
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
    # Enabling is a separate controller operation after full runtime qualification.
    if not state['execution_authorized'] or not route['enabled']:
        return 'paused'
    key=(source,unit_id,unit['revision'])
    marker=ledger.digest(dict(source_task=source,unit=unit_id,revision=unit['revision'],
        issue_id=issue,binding=unit['binding'],operation='incremental-tests-only'))
    prior=con.execute('SELECT marker,state FROM incremental_dispatch_intents WHERE source_task=? AND unit=? AND revision=?',key).fetchone()
    intent=json.loads(prior[1]) if prior else {'stage':'pending','at':now}
    if prior and prior[0]!=marker:raise ValueError('dispatch marker drift')
    if intent['stage'] in ('dispatched','blocked'):return intent['stage']
    if now-intent['at']>=600:
        intent.update(stage='blocked',owner=route['cto'],category='unit_dispatch_unattended',
                      required_action='diagnose_dispatch_capacity_or_transport')
    elif effects.remaining_calls()<route['minimum_calls']:
        intent.update(stage='budget_wait',owner='controller')
    elif not effects.implementation_available(issue,route['author']):
        intent.update(stage='capacity_wait',owner='controller')
    else:
        intent.update(stage='dispatch_intent',owner=route['author'])
    con.execute('INSERT OR REPLACE INTO incremental_dispatch_intents VALUES(?,?,?,?,?)',
                (*key,marker,json.dumps(intent,sort_keys=True)))
    con.commit()  # remote side effect MUST follow durable intent
    if intent['stage']!='dispatch_intent':return intent['stage']
    spec=next(u for u in config['units'] if u['id']==unit_id)
    note=('CONTROLLER INCREMENTAL TESTS ONLY '+unit_id+' revision '+str(unit['revision'])+
          '. New test: '+unit['binding']['materialization']['new_test']+
          '. Preserve all existing code and tests. Do not implement yet. Objective: '+spec['objective']+
          '. Criteria: '+','.join(spec['criteria'])+'. Use the complete pinned suite; no textual Red claims. '
          'Follow its pinned test framework: for python3 -m unittest use unittest.TestCase '
          'and test_ methods, not pytest imports, fixtures, decorators or a new dependency. '
          'A collection/import error is not valid Red. Do not install dependencies or change the runner.')
    if unit.get('test_repair'):
        repair = unit['test_repair']
        note += (' Controller-sponsored NEW-test harness repair; not permission to weaken assertions. '
                 'Inspect seeded prior NEW tests. Preserve methods, assertions and criteria; repair only '
                 'the diagnosed NEW-test fixture or harness and required NEW negative-control tests. '
                 'Do not modify product code or baseline tests. CTO diagnosis (not approval): '+repair['reason'])
        if repair.get('operation')=='cto_source_harness_revision_v1':
            note += (' Preserve all seeded substantive assertions. Repair only the verified NEW harness '
                'chronology, request resolution and faithful POST data. Add executable negative controls '
                'demonstrating that clearing a query on refresh and painting stale query/status responses '
                'are rejected. Run the real client through the harness, not regex or fabricated reports. '
                'Do not modify product code, baseline tests or pinned runner. This revision needs fresh '
                'controller Red and independent review; prior approval does not transfer.')
        if repair.get('operation') in ('cto_harness_experiment_revision_v1','cto_seed_transport_revision_v1','cto_negative_controls_revision_v1'):
            note += (' Verified experiment '+repair['experiment_sha256']+
                ': fake querySelectorAll lacks attribute selectors, both quoted and unquoted. '
                'Implement real tag/attribute matching in the NEW-test DOM harness; removing quotes alone fails. '
                'Preserve every historical assertion expression and test method. Add executable negative '
                'control tests for wrong input type, input inside form and wrong accessible label. '
                'Keep the canonical input[type="search"] query. Controller runs fixed positive and '
                'negative controls on your unmodified harness before independent review. No product workaround.')
        if repair.get('operation')=='cto_negative_controls_revision_v1':
            note += (' The previous revision preserved two methods/eight assertions but added ZERO negative-control methods. '
                'Do not submit only harness edits again. Add actual NEW test_ methods asserting incorrect input type, '
                'incorrect accessible label and position inside the form are rejected, using real Node execution. '
                'Keep every seeded existing method/assertion unchanged. Do not hardcode reports or assert True. '
                'Run the complete pinned Red suite and submit the tests-only artifact; no product implementation yet.')
        if repair.get('operation')=='cto_negative_spike_revision_v1':
            note += (' Verified read-only Node SPIKE '+repair['negative_spike_sha256']+
                ': repair parseFragment quoted attribute capture groups a[2]/a[3]/a[4] and add form containment '
                'to acceptsSearchInput. Preserve ALL six seeded test methods and every assertion unchanged. '
                'No extra test method is required for this helper-only correction. Do not change product or baseline tests. '
                'Execute every negative control and full pinned Red suite; controller v2 admission independently verifies them.')
    # An ambiguous exception leaves intent intact; native lookup recovers the
    # existing wakeup rather than sending an unrelated retry.
    try:
        wake=effects.ensure_unit_start(issue,route['author'],source,marker,note,allow_create=True)
    except Exception as error:
        category=type(error).__name__
        count=intent.get('same_failure_count',0)+1 if intent.get('last_failure')==category else 1
        intent.update(last_failure=category,same_failure_count=count)
        if count>=2:
            intent.update(stage='blocked',owner=route['cto'],category='repeated_dispatch_failure',
                          required_action='reconcile_remote_wakeup_then_diagnose')
        con.execute('UPDATE incremental_dispatch_intents SET state=? WHERE source_task=? AND unit=? AND revision=?',
                    (json.dumps(intent,sort_keys=True),*key));con.commit()
        return intent['stage']
    if wake is None:return 'dispatch_intent'
    intent.update(stage='dispatched',wakeup_id=wake['id'])
    con.execute('UPDATE incremental_dispatch_intents SET state=? WHERE source_task=? AND unit=? AND revision=?',
                (json.dumps(intent,sort_keys=True),*key));con.commit()
    return 'dispatched'
