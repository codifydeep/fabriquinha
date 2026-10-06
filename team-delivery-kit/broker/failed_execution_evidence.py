"""One bounded evidence enrichment; never overwrite an earlier diagnosis."""
import hashlib
import json
import re
import time


def register(broker, payload):
    if (not isinstance(payload, dict) or set(payload) != {'source_task', 'decision_task', 'output_sha256'}
            or any(not isinstance(payload[k], str) or not re.fullmatch(r'[a-f0-9-]{36}', payload[k])
                   for k in ('source_task', 'decision_task'))
            or not isinstance(payload['output_sha256'], str)
            or not re.fullmatch(r'[a-f0-9]{64}', payload['output_sha256'])):
        raise ValueError('exact failed source, decision and saved output required')
    try:
        import native, handoffs
    except ImportError:
        from broker import native, handoffs
    source = payload['source_task']
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS failed_execution_evidence('
                    'source_task TEXT PRIMARY KEY,receipt TEXT)')
        old = con.execute('SELECT receipt FROM failed_execution_evidence WHERE source_task=?', (source,)).fetchone()
        if old:
            receipt = json.loads(old[0])
            if receipt['request'] != payload:
                raise ValueError('evidence enrichment already used')
            return receipt
        row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
        if not row or row['stage'] != 'technical_decision_required':
            raise ValueError('blocked CTO diagnosis required')
        data = json.loads(row['data'])
        diagnosis = data.get('failed_execution_diagnostic') or {}
        failure = data.get('validation_failure') or {}
        recorded = con.execute('SELECT receipt FROM failed_execution_diagnoses WHERE source_task=?', (source,)).fetchone()
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (row['issue_id'],)).fetchone()[0])
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()[0]
        if (not recorded or json.loads(recorded[0]) != diagnosis or diagnosis.get('failure') != failure
                or failure.get('output_sha256') != payload['output_sha256']
                or data.get('recipient_task') != payload['decision_task']
                or data.get('target') != route['cto'] or data.get('decision', {}).get('action') != 'escalate_cto'
                or latest != source or route['enabled']
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone()):
            raise ValueError('current immutable failed source and paused idle CTO decision required')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, row['issue_id'])
        decision = next((r for r in runs if r['id'] == payload['decision_task']), None)
        if (not decision or decision.get('status') != 'completed' or decision.get('agent_id') != route['cto']
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('completed CTO and idle native tasks required')
        saved = con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
                            (source, payload['output_sha256'])).fetchone()
        if not saved or hashlib.sha256(saved[0].encode()).hexdigest() != payload['output_sha256']:
            raise ValueError('saved suite output missing or changed')
        red = json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
                                     (row['issue_id'],)).fetchone()[0])
        snapshot = con.execute('SELECT volume FROM failed_execution_snapshots WHERE task_id=? AND status=?',
                               (source, 'complete')).fetchone()
        if not snapshot or snapshot[0] != diagnosis['volume']:
            raise ValueError('diagnostic snapshot missing')
        volume = broker.docker('GET', '/volumes/' + snapshot[0])
        labels = volume.get('Labels', {}) if volume else {}
        if (labels.get('delivery-kit.owner') != broker.OWNER
                or labels.get('delivery-kit.source-task') != source
                or labels.get('delivery-kit.diagnostic-only') != 'true'):
            raise ValueError('diagnostic snapshot identity mismatch')
        proof = capture(broker, source, snapshot[0], red['red']['test_sha256'], saved[0])
        if proof['output_sha256'] != payload['output_sha256'] or not proof['witnesses']:
            raise ValueError('no new bounded assertion witnesses')
        receipt = {'request': payload, 'volume': snapshot[0], 'proof': proof,
                   'prior_decision': data['decision'], 'status': 'evidence_only_not_approved'}
        data.update(assertion_evidence=receipt, diagnostic_revision=proof['output_sha256'] + ':assertions-v1',
                    trigger_task=payload['decision_task'])
        for field in ('wakeup_id', 'recipient_task', 'dispatched_at', 'dispatch_marker',
                      'dispatch_stage', 'target', 'instruction', 'decision',
                      'control_error', 'control_error_count', 'alerted'):
            data.pop(field, None)
        con.execute('INSERT INTO failed_execution_evidence VALUES (?,?)', (source, json.dumps(receipt, sort_keys=True)))
        handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], data, time.time())
        return receipt


def clear_superseded_trace_blocker(data,receipt):
    """Archive only the exact enrichment blocker superseded by verified evidence."""
    result=dict(data);blocked=result.get('trace_auto_failure') or {}
    if (receipt and result.get('membership_trace_evidence')==receipt
            and result.get('assertion_trace_evidence')==receipt
            and blocked.get('stage')=='blocked'
            and result.get('required_action')==blocked.get('required_action')
            and blocked.get('required_action')=='diagnose_fixed_trace_experiment_without_identical_retry'):
        result['prior_trace_auto_failure']=result.pop('trace_auto_failure')
        result.pop('required_action',None)
    return result


def reconcile_trace(broker,row,*,membership=False):
    """One automatic evidence experiment after an escalated completed failure."""
    try:import handoffs
    except ImportError:from broker import handoffs
    data=json.loads(row['data'])
    receipt=data.get('membership_trace_evidence')
    visible=clear_superseded_trace_blocker(data,receipt)
    if visible!=data:
        with broker.db() as con:
            stored=con.execute('SELECT receipt FROM completed_membership_traces WHERE source_task=?',(row['source_task'],)).fetchone()
            current=handoffs.load(con,row['source_task'])
            if stored and json.loads(stored[0])==receipt and current and current['data']==row['data'] and current['stage']==row['stage']:
                handoffs.save(con,row['source_task'],current['issue_id'],current['stage'],current['owner'],visible,time.time())
                return True
    if (row['stage']!='technical_decision_required' or not data.get('artifact_diagnosis')
            or (data.get('validation_failure') or {}).get('category')!='executed_test_failure'
            or (data.get('decision') or {}).get('action')!='escalate_cto'
            or any(k in data for k in ('failed_execution_diagnostic','lost_execution_diagnostic'))):return False
    if membership:
        if not data.get('assertion_trace_evidence') or data.get('membership_trace_evidence'):return False
    elif 'assertion_trace_evidence' in data:return False
    source=row['source_task']
    table='completed_membership_attempts_v2' if membership else 'completed_trace_attempts'
    with broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS '+table+'(source_task TEXT PRIMARY KEY,state TEXT)')
        saved=con.execute('SELECT state FROM '+table+' WHERE source_task=?',(source,)).fetchone()
        state=json.loads(saved[0]) if saved else dict(stage='intent',starts=0,delivery_approval=False)
        if state['stage'] in ('complete','blocked'):return True
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return True
        if state['starts']>=2:state.update(stage='blocked',failure_category='InterruptedExperiment',required_action='reconcile_interrupted_trace_without_identical_retry')
        else:state['starts']+=1
        con.execute('INSERT OR REPLACE INTO '+table+' VALUES(?,?)',(source,json.dumps(state,sort_keys=True)))
        con.commit()
    if state['stage']!='blocked':
        try:
            receipt=register_trace(broker,source,membership=True) if membership else register_trace(broker,source)
            state.update(stage='complete',manifest_sha256=receipt['proof']['manifest_sha256'])
        except Exception as error:
            state.update(stage='blocked',failure_category=type(error).__name__,required_action='diagnose_fixed_trace_experiment_without_identical_retry')
    with broker.db() as con:
        con.execute('UPDATE '+table+' SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        if state['stage']=='blocked':
            handoffs.initialize(con);current=handoffs.load(con,source)
            if current and current['stage']=='technical_decision_required':
                visible=json.loads(current['data']);visible['trace_auto_failure']=state;visible['required_action']=state['required_action']
                handoffs.save(con,source,current['issue_id'],current['stage'],current['owner'],visible,time.time())
    return True


def register_trace(broker,source,*,membership=False):
    """One changed-evidence diagnosis of an ordinary completed frozen failure."""
    import os
    try:import native,handoffs
    except ImportError:from broker import native,handoffs
    table='completed_membership_traces' if membership else 'completed_failure_traces'
    with broker.LOCK:
        with broker.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS '+table+'(source_task TEXT PRIMARY KEY,receipt TEXT)')
            old=con.execute('SELECT receipt FROM '+table+' WHERE source_task=?',(source,)).fetchone()
            if old:return json.loads(old[0])
            row=handoffs.load(con,source);data=json.loads(row['data']) if row else {}
            failure=data.get('validation_failure') or {}
            if (not row or row['stage']!='technical_decision_required' or not data.get('artifact_diagnosis')
                    or failure.get('category')!='executed_test_failure' or failure.get('source_task')!=source
                    or (data.get('decision') or {}).get('action')!='escalate_cto'):
                raise ValueError('exact escalated executed failure required')
            if membership and (not data.get('assertion_trace_evidence') or data.get('membership_trace_evidence')):
                raise ValueError('one prior trace without membership upgrade required')
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            if data.get('target')!=route['cto']:raise ValueError('CTO diagnosis required')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle trace capture required')
            latest=con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(row['issue_id'],)).fetchone()[0]
            binding=con.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? ORDER BY n.rowid DESC LIMIT 1',(source,)).fetchone()
            snapshot=con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",(source,)).fetchone()
            if latest!=source or not binding or binding[0]!='closed' or not snapshot or snapshot[0]!=failure['volume']:
                raise ValueError('current closed immutable author required')
            saved=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',(source,failure['output_sha256'])).fetchone()
            if not saved or hashlib.sha256(saved[0].encode()).hexdigest()!=failure['output_sha256']:raise ValueError('fixed saved failure output required')
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        settings=json.loads((broker.STATE/'native.json').read_text())
        author=native.task_record(settings,source,route['author'])
        cto=native.task_record(settings,data['recipient_task'],route['cto'])
        if (author['status']!='completed' or author['issue_id']!=row['issue_id'] or cto['status']!='completed'
                or cto['issue_id']!=row['issue_id'] or cto.get('wakeup_id')!=data['wakeup_id']
                or any(r['status'] in ('running','queued') for r in native.issue_task_runs(settings,row['issue_id']))):
            raise ValueError('actual idle completed author and CTO required')
        labels=broker.docker('GET','/volumes/'+snapshot[0]).get('Labels',{})
        if labels.get('delivery-kit.owner')!=broker.OWNER or labels.get('delivery-kit.source-task')!=source:
            raise ValueError('trace snapshot labels drift')
        image=broker.docker('GET','/containers/'+os.environ['HOSTNAME']+'/json')['Image']
        proof=capture(broker,source,snapshot[0],red['red']['test_sha256'],saved[0],trace=True,image=image)
        if proof['output_sha256']!=failure['output_sha256'] or not proof['anchors']:
            raise ValueError('new hash-bound trace anchors required')
        if membership and (not any('membership' in a for a in proof['anchors']) or proof==data['assertion_trace_evidence']['proof']):
            raise ValueError('new verified membership operands required; identical replay prohibited')
        receipt=dict(source_task=source,issue_id=row['issue_id'],volume=snapshot[0],proof=proof,
            prior_cto_task=cto['id'],prior_decision=data['decision'],helper_image=image,delivery_approval=False)
        if membership:receipt['prior_trace']=data['assertion_trace_evidence']
        with broker.db() as con:
            current=handoffs.load(con,source)
            if current['stage']!=row['stage'] or current['data']!=row['data']:raise ValueError('trace handoff drift')
            con.execute('INSERT INTO '+table+' VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            if membership:
                data['membership_trace_evidence']=receipt
            data.update(assertion_trace_evidence=receipt,trigger_task=cto['id'],diagnostic_revision=proof['output_sha256']+(':membership-operands-v1' if membership else ':trace-anchors-v1'))
            data=clear_superseded_trace_blocker(data,receipt)
            for key in ('wakeup_id','recipient_task','dispatched_at','dispatch_marker','dispatch_stage','target','instruction','decision','control_error','control_error_count'):data.pop(key,None)
            handoffs.save(con,source,row['issue_id'],'diagnose_cto',route['cto'],data,time.time())
        return receipt


def capture(broker, source, volume, hashes, output, *, semantic=False, scope=None,trace=False,image=None):
    if trace and (semantic or scope is not None or not isinstance(image,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',image)):
        raise ValueError('fixed immutable trace helper required')
    if scope is not None and not semantic:
        raise ValueError('semantic scope requires fixed semantic operation')
    name = broker.PREFIX + ('-semantic-witness-' if semantic else '-assertion-witness-') + source
    prior = broker.docker('GET', '/containers/' + name + '/json')
    if prior:
        if prior['Config'].get('Labels', {}).get('delivery-kit.source-task') != source:
            raise ValueError('foreign assertion probe')
        broker.docker('DELETE', '/containers/' + prior['Id'] + '?force=true')
    broker.docker('POST', '/containers/create?name=' + name, {
        'Image': image if trace else broker.IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
        'Cmd': ['/semantic_fixture_probe.py' if semantic else '/assertion_witness.py'], 'NetworkDisabled': True,
        'Env': ['SAVED_OUTPUT=' + json.dumps(output), 'FROZEN_TEST_HASHES=' + json.dumps(hashes)]
               + (['SEMANTIC_SCOPE=' + json.dumps(scope)] if scope is not None else [])
               + (['ASSERTION_TRACE=1'] if trace else []),
        'Labels': {'delivery-kit.owner': broker.OWNER, 'delivery-kit.source-task': source,
                   'com.docker.compose.project': broker.PREFIX},
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                       'SecurityOpt': ['no-new-privileges'], 'Memory': 67108864, 'PidsLimit': 16,
                       'Mounts': [{'Type': 'volume', 'Source': volume, 'Target': '/delivery', 'ReadOnly': True}]}})
    try:
        broker.docker('POST', '/containers/' + name + '/start')
        deadline = time.time() + 20
        while time.time() < deadline:
            info = broker.docker('GET', '/containers/' + name + '/json')
            if info and not info['State']['Running']:
                if info['State']['ExitCode']:
                    raise ValueError('assertion witness probe rejected evidence')
                result = json.loads(broker.docker_stdout(name))
                keys = {'manifest_sha256', 'output_sha256', 'witnesses', 'fixture_literals_only'}
                if semantic:
                    keys |= {'facts', 'operation', 'status', 'contradictions'}
                if trace:keys|={'anchors','operation','approval'}
                if trace and (result.get('approval') is not False or result.get('operation')!='frozen_assertion_trace_anchors_v1'):
                    raise ValueError('trace is not approval')
                if (set(result) != keys
                        or result['fixture_literals_only'] is not True
                        or not re.fullmatch(r'[a-f0-9]{64}', result['manifest_sha256'])):
                    raise ValueError('invalid assertion witness proof')
                return result
            time.sleep(.2)
        raise TimeoutError('assertion witness probe deadline')
    finally:
        broker.docker('DELETE', '/containers/' + name + '?force=true')
