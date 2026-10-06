"""One CTO replan of a controller-proven harness defect; no author retry."""
import json
import time
try:
    import native,handoff_runtime,incremental_checkpoints as ledger
except ImportError:
    from broker import native,handoff_runtime,incremental_checkpoints as ledger


def validate_experiment(proof, hashes):
    try:from harness_selector_spike import validate_reports,TEST
    except ImportError:from broker.harness_selector_spike import validate_reports,TEST
    if (proof.get('operation')!='actual_node_attribute_selector_spike_v1'
            or proof.get('conclusion')!='harness_lacks_attribute_selector_support_confirmed_by_controls'
            or proof.get('repository_modified') is not False or proof.get('delivery_approval') is not False
            or proof.get('input_sha256',{}).get(TEST)!=hashes.get(TEST)):
        raise ValueError('verified same-test selector experiment required')
    ledger._hash(proof.get('manifest_sha256'))
    validate_reports(proof['reports'])


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS incremental_harness_replans('
                'source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def instruction(config):
    proof=config['experiment']
    summary={n:proof['reports'][n] for n in ('original_quoted','equivalent_unquoted',
        'adapted_original_quoted','adapted_wrong_type_control','adapted_inside_form_control','adapted_wrong_label_control')}
    return ('DELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'CTO REPLAN: controller ran an actual isolated Node experiment; no author artifacts changed. '
        'Experiment SHA '+config['experiment_sha256']+'. Results: '+json.dumps(summary,separators=(',',':'))+
        '\nThe fake querySelectorAll lacks attribute selectors; removing CSS quotes alone does not fix it. '
        'A diagnostic in-memory selector adapter passes positive and negative controls. '
        'The author resubmitted byte-identical tests and reviewer incorrectly approved; that approval '
        'is invalidated and preserved. Decide whether to sponsor a NEW original-base test revision. '
        'It must implement actual attribute-selector matching in the fake DOM, preserve every test '
        'method/assertion and add negative controls for type, label and position. Do not change product '
        'code to accommodate a fake DOM. Baseline tests immutable. No approval, merge or deploy. '
        'Return ONLY JSON: action=request_test_revision or escalate_cto, reason<=1200 characters, '
        'optional_files=[]. No tools; these are controller-executed facts, not your own execution claims.')


def arm(b,source):
    with b.LOCK,b.db() as con:
        initialize(con)
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle replan window required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1'];issue=unit['binding']['issue_id']
        incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()[0])
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        proof=json.loads(con.execute('SELECT receipt FROM incremental_harness_experiments WHERE source_task=? AND revision=?',(source,unit['revision'])).fetchone()[0])
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
        if (unit['revision']!=2 or not unit.get('test_repair') or route['enabled']
                or incident.get('category')!='unchanged_seed_after_sponsored_repair'
                or incident.get('harness_experiment_sha256')!=ledger.digest(proof)
                or incident.get('owner')!=route['cto']):
            raise ValueError('paused experiment-bound unchanged-repair incident required')
        validate_experiment(proof,trial['old_red']['red']['test_sha256'])
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,issue)
        if any(r.get('status') in ('queued','running') for r in runs):raise ValueError('idle native issue required')
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        trigger=max(authors,key=lambda r:(r.get('created_at') or '',r['id']))
        if trigger['status']!='completed':raise ValueError('exact completed triggering author required')
        record=dict(source_task=source,issue_id=issue,revision=2,cto=route['cto'],
            trigger_task=trigger['id'],experiment=proof,experiment_sha256=ledger.digest(proof))
        marker=ledger.digest(record);record['marker']=marker
        prior=con.execute('SELECT config,state FROM incremental_harness_replans WHERE source_task=?',(source,)).fetchone()
        if prior:
            if json.loads(prior[0])!=record:raise ValueError('immutable replan drift')
            return json.loads(prior[1])
        instruction(record)  # bounded before side effects
        con.execute('INSERT INTO incremental_harness_replans VALUES(?,?,?)',
                    (source,json.dumps(record,sort_keys=True),json.dumps({'stage':'pending','delivery_approval':False})))
        return {'stage':'pending','delivery_approval':False}


def tick(b,source):
    try:return _tick(b,source)
    except Exception as error:
        with b.db() as con:
            row=con.execute('SELECT state FROM incremental_harness_replans WHERE source_task=?',(source,)).fetchone()
            if not row:raise
            state=json.loads(row[0]);count=state.get('controller_failure_count',0)+1
            state.update(controller_failure_count=count,controller_failure_category=type(error).__name__,
                         required_action='reconcile_native_replan_identity_and_transport')
            if count>=2:state['stage']='blocked'
            con.execute('UPDATE incremental_harness_replans SET state=? WHERE source_task=?',
                        (json.dumps(state,sort_keys=True),source))
        return state


def _tick(b,source):
    with b.LOCK,b.db() as con:
        initialize(con)
        row=con.execute('SELECT config,state FROM incremental_harness_replans WHERE source_task=?',(source,)).fetchone()
        if not row:return
        config,state=map(json.loads,row)
    if state['stage'] in ('sponsored','blocked'):return state
    settings=json.loads((b.STATE/'native.json').read_text())
    effects=handoff_runtime.Effects(b,settings)
    if not state.get('wakeup_id'):
        if effects.remaining_calls()<4:return state
        wake=effects.ensure_wakeup(config['issue_id'],config['cto'],config['trigger_task'],
            config['marker'],instruction(config),allow_create=True)
        if not wake:return state
        state.update(stage='awaiting_cto',wakeup_id=wake['id'])
        _save(b,source,state)
    tasks=[r for r in native.issue_task_runs(settings,config['issue_id']) if r.get('wakeup_id')==state['wakeup_id']]
    if not tasks or any(t['status'] in ('queued','running') for t in tasks):return state
    if len(tasks)!=1 or tasks[0]['status']!='completed' or tasks[0].get('agent_id')!=config['cto']:
        state.update(stage='blocked',category='cto_replan_execution_failed');_save(b,source,state);return state
    task=native.task_record(settings,tasks[0]['id'],config['cto'])
    decision=effects.decision(task)
    if decision['action'] not in ('request_test_revision','escalate_cto') or decision['optional_files']:
        raise ValueError('bounded CTO replan decision required')
    state.update(stage='sponsored' if decision['action']=='request_test_revision' else 'blocked',
                 task_id=task['id'],decision=decision,experiment_sha256=config['experiment_sha256'])
    _save(b,source,state)
    return state


def _save(b,source,state):
    with b.db() as con:
        con.execute('UPDATE incremental_harness_replans SET state=? WHERE source_task=?',
                        (json.dumps(state,sort_keys=True),source))


def prepare_revision(b,source,fixture_volume):
    """Atomic ledger/handoff transition from the real, completed CTO replan."""
    with b.LOCK,b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle experiment revision window required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1']
        if unit['revision']==3:
            receipt=unit['test_repair']
            if receipt['fixture_volume']!=fixture_volume:raise ValueError('immutable fixture identity drift')
            return receipt
        plan,result=map(json.loads,con.execute('SELECT config,state FROM incremental_harness_replans WHERE source_task=?',(source,)).fetchone())
        incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()[0])
        issue=unit['binding']['issue_id']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
        validate_experiment(plan['experiment'],trial['old_red']['red']['test_sha256'])
        if (result.get('stage')!='sponsored' or route['enabled'] or plan['issue_id']!=issue
                or plan['revision']!=2 or plan['cto']!=route['cto']
                or result.get('experiment_sha256')!=ledger.digest(plan['experiment'])
                or incident.get('category')!='unchanged_seed_after_sponsored_repair'
                or incident.get('harness_experiment_sha256')!=result['experiment_sha256']):
            raise ValueError('same paused incident and actual sponsorship required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,result['task_id'],route['cto'])
        decision=handoff_runtime.Effects(b,settings).decision(task)
        if (task.get('status')!='completed' or task.get('issue_id')!=issue
                or task.get('wakeup_id')!=result['wakeup_id'] or decision!=result['decision']
                or decision['action']!='request_test_revision' or decision['optional_files']):
            raise ValueError('exact native CTO experiment decision required')
        if any(r.get('status') in ('queued','running') for r in native.issue_task_runs(settings,issue)):
            raise ValueError('idle native revision required')
        volume=b.docker('GET','/volumes/'+fixture_volume)
        if not volume or volume.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER:
            raise ValueError('owned experiment fixture required')
        receipt=dict(operation='cto_harness_experiment_revision_v1',source_task=source,unit='U1',
            parent_issue=issue,decision_task=task['id'],cto=route['cto'],original_red=unit['red'],
            proposal_sha256=config['proposal_sha256'],reason=decision['reason'],
            experiment_sha256=result['experiment_sha256'],fixture_volume=fixture_volume)
        # Preserve the failed author handoff. New sponsorship belongs to the CTO task.
        data=dict(target=route['cto'],wakeup_id=result['wakeup_id'],decision=decision,
            harness_selector_experiment=plan['experiment'],harness_fixture_volume=fixture_volume,
            test_revision_proposal=dict(decision_task=task['id'],source_task=task['id'],
                reason=decision['reason'],new_test_files=route['test_first_files']),delivery_approval=False)
        with ledger._atomic(con):
            ledger.prepare_harness_revision(con,source,ledger.digest(receipt),lambda _:receipt)
            encoded=json.dumps(data,sort_keys=True)
            con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?,?)',
                (task['id'],issue,'test_revision_required',route['cto'],encoded,time.time()))
            con.execute('INSERT INTO delivery_handoff_events(source_task,stage,data,at) VALUES(?,?,?,?)',
                (task['id'],'test_revision_required',encoded,time.time()))
            # Archive rather than conceal the invalid approval incident.
            con.execute('CREATE TABLE IF NOT EXISTS incremental_runtime_incident_archive('
                'source_task TEXT,revision INTEGER,receipt TEXT,PRIMARY KEY(source_task,revision))')
            con.execute('INSERT INTO incremental_runtime_incident_archive VALUES(?,?,?)',
                (source,2,json.dumps(incident,sort_keys=True)))
            con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=?',(source,))
        return receipt
