"""One changed-contract recovery for a proven empty tests-only artifact."""
import hashlib
import json
import time
import uuid
import re


def reopen(broker, payload):
    try:
        import native, handoffs, handoff_runtime
    except ImportError:
        from broker import native, handoffs, handoff_runtime
    fields = {'issue_id', 'source_task', 'cto_task', 'worker_image'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('exact artifact recovery identity required')
    for key in ('issue_id', 'source_task', 'cto_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('invalid recovery identity')
    if payload['worker_image'] != broker.IMAGE or not payload['worker_image'].startswith('sha256:'):
        raise ValueError('installed immutable recovery image required')
    with broker.LOCK:
        with broker.db() as con:
            prior = handoffs.load(con, payload['source_task'])
            if not prior or prior['issue_id'] != payload['issue_id']:
                raise ValueError('blocked artifact missing')
            data = json.loads(prior['data'])
            if data.get('artifact_recovery'):
                if data['artifact_recovery']['request'] != payload:
                    raise ValueError('artifact recovery identity drift')
                return data['artifact_recovery']
            rows = con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',
                               (payload['issue_id'],)).fetchall()
            if any(json.loads(row[0]).get('artifact_recovery') for row in rows):
                raise ValueError('artifact recovery already consumed for issue')
            route_row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                    (payload['issue_id'],)).fetchone()
            route = json.loads(route_row[0]) if route_row else {}
            if (prior['stage'] != 'test_first_blocked'
                    or data.get('error') != 'test_first_correction_failed_after_cto_diagnosis'
                    or not route.get('enabled') or not route.get('test_first')):
                raise ValueError('only blocked empty-artifact correction may recover')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',
                           (payload['issue_id'],)).fetchone():
                raise ValueError('Red already exists; artifact recovery forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
                raise ValueError('artifact recovery requires idle workers')
        markers = broker.test_artifact_phase_context(payload['issue_id'], route['author'])
        if not markers.startswith('\nDELIVERY_TEST_ARTIFACT_V1:'):
            raise ValueError('changed artifact gate must be enabled')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        source = next((r for r in authors if r['id'] == payload['source_task']), {})
        cto = next((r for r in runs if r['id'] == payload['cto_task']), {})
        if (not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source.get('id')
                or source.get('status') != 'completed' or cto.get('status') != 'completed'
                or cto.get('agent_id') != route['cto'] or route['cto'] == route['author']
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('latest idle author and independent CTO required')
        sponsors = [json.loads(r[0]) for r in rows if
                    json.loads(r[0]).get('cto_task') == payload['cto_task']
                    and json.loads(r[0]).get('test_first_correction_wakeup') == source.get('wakeup_id')]
        effects = handoff_runtime.Effects(broker, settings)
        decision = effects.decision(cto)
        if (len(sponsors) != 1 or decision != sponsors[0].get('decision')
                or decision.get('action') != 'request_correction' or decision.get('optional_files') != []):
            raise ValueError('exact existing CTO correction sponsorship required')
        # A fixed controller snapshot rechecks workspace fences and hashes. The
        # rejected artifact must still be empty; never fabricate a Red receipt.
        try:
            broker.capture_test_first_red({'task_id': source['id']})
        except ValueError:
            pass
        else:
            raise ValueError('valid Red now exists; artifact recovery forbidden')
        diagnostic = json.loads((broker.STATE / 'test-first-incidents' / (source['id'] + '.json')).read_text())
        files = diagnostic.get('files', {})
        target = route.get('test_first_files', [])
        if (diagnostic.get('issue_id') != payload['issue_id'] or diagnostic.get('task_id') != source['id']
                or diagnostic.get('kind') != 'rejected_snapshot' or diagnostic.get('category') != 'empty_new_test'
                or len(target) != 1 or set(files) != set(target)
                or any(f.get('bytes') != 0 or f.get('sha256') != hashlib.sha256(b'').hexdigest()
                       for f in files.values())):
            raise ValueError('fresh exact empty-test snapshot evidence required')
        receipt = {'request': payload, 'at': time.time(), 'decision': decision,
                   'previous_blocker': data.copy(), 'diagnostic': diagnostic,
                   'contract': 'observed-source-read-verified-test-write-v1',
                   'contract_sha256': hashlib.sha256((payload['worker_image'] + markers).encode()).hexdigest()}
        data['artifact_recovery'] = receipt
        with broker.db() as con:
            handoffs.save(con, source['id'], payload['issue_id'], 'test_first_artifact_recovery_pending',
                          route['author'], data, time.time())
        return receipt


def reopen_provider(broker, payload):
    """One pre-tool provider repair, never another empty-artifact retry."""
    try:
        import native, handoffs
        from model_policy import MODEL
    except ImportError:
        from broker import native, handoffs
        from model_policy import MODEL
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'failed_task', 'probe'}:
        raise ValueError('exact provider recovery identity required')
    for key in ('issue_id', 'failed_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('invalid provider identity')
    proof = payload['probe']
    if (not isinstance(proof, dict) or proof.get('schema') != 'artifact-provider-probe-v1'
            or proof.get('status') != 'passed' or proof.get('model') != MODEL
            or proof.get('executed') is not False or proof.get('delivery_approval') is not False
            or proof.get('phases') != [{'phase': 'read', 'arguments_valid': True},
                                     {'phase': 'write', 'arguments_valid': True}]
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(proof.get('proxy_image', '')))
            or not re.fullmatch(r'[0-9a-f]{64}', str(proof.get('gate_sha256', '')))):
        raise ValueError('successful bound synthetic provider probe required')
    with broker.LOCK:
        with broker.db() as con:
            prior = handoffs.load(con, payload['failed_task'])
            if not prior or prior['issue_id'] != payload['issue_id']:
                raise ValueError('failed provider handoff missing')
            data = json.loads(prior['data'])
            if data.get('provider_recovery'):
                if data['provider_recovery']['request'] != payload:
                    raise ValueError('provider recovery identity drift')
                return data['provider_recovery']
            rows = con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',
                               (payload['issue_id'],)).fetchall()
            if any(json.loads(r[0]).get('provider_recovery') for r in rows):
                raise ValueError('provider repair already consumed for issue')
            repairs = [json.loads(r[0]) for r in rows if json.loads(r[0]).get('artifact_recovery')]
            route_row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (payload['issue_id'],)).fetchone()
            route = json.loads(route_row[0]) if route_row else {}
            if (len(repairs) != 1 or prior['stage'] != 'test_first_blocked'
                    or not route.get('enabled') or not route.get('test_first')):
                raise ValueError('blocked changed-contract execution required')
            repair = repairs[0]
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?', (payload['issue_id'],)).fetchone():
                raise ValueError('Red exists; provider bootstrap repair forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
                raise ValueError('provider repair requires idle workers')
            bindings = con.execute('SELECT scope,agent_id FROM native_bindings WHERE task_id IN (?,?)',
                                   (payload['failed_task'], repair['artifact_recovery']['request']['source_task'])).fetchall()
            if (len(bindings) != 2 or len({r['scope'] for r in bindings}) != 1
                    or any(r['agent_id'] != route['author'] for r in bindings)):
                raise ValueError('exact preserved author workspace required')
        proxy = broker.docker('GET', '/containers/' + broker.PREFIX + '-model-proxy-1/json')
        if (proxy.get('Image') != proof['proxy_image'] or not proxy.get('State', {}).get('Running')
                or proxy.get('Config', {}).get('Labels', {}).get('com.docker.compose.project') != broker.PREFIX):
            raise ValueError('provider probe does not match installed scoped proxy')
        if not broker.test_artifact_phase_context(payload['issue_id'], route['author']):
            raise ValueError('artifact gate disabled')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        failed = next((r for r in authors if r['id'] == payload['failed_task']), {})
        if (not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != failed.get('id')
                or failed.get('status') != 'failed'
                or failed.get('error') != 'hermes provider error: API call failed after 1 retries'
                or failed.get('wakeup_id') != repair.get('artifact_recovery_wakeup')
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('exact idle pre-tool provider failure required')
        messages = native.task_messages(settings, failed['id'])
        if not messages or any(m.get('type') in ('tool_use', 'tool_result') or m.get('tool_calls') for m in messages):
            raise ValueError('provider repair forbidden after tool activity')
        source = repair['artifact_recovery']['request']['source_task']
        try:
            broker.capture_test_first_red({'task_id': source})
        except ValueError:
            pass
        else:
            raise ValueError('valid Red now exists; recovery forbidden')
        diagnostic = json.loads((broker.STATE / 'test-first-incidents' / (source + '.json')).read_text())
        if (diagnostic.get('issue_id') != payload['issue_id'] or diagnostic.get('task_id') != source
                or diagnostic.get('category') != 'empty_new_test'
                or diagnostic.get('files') != repair['artifact_recovery']['diagnostic']['files']):
            raise ValueError('preserved empty artifact changed')
        receipt = {'request': payload, 'at': time.time(), 'previous_blocker': data.copy(),
                   'decision': repair['artifact_recovery']['decision'], 'diagnostic': diagnostic,
                   'original_source': source, 'cto_task': repair['artifact_recovery']['request']['cto_task'],
                   'artifact_contract': repair['artifact_recovery'],
                   'kind': 'pre_tool_provider_repair_v1'}
        data['provider_recovery'] = receipt
        with broker.db() as con:
            handoffs.save(con, failed['id'], payload['issue_id'], 'test_first_provider_recovery_pending',
                          route['author'], data, time.time())
        return receipt


def replan_framework(broker, payload):
    """One new technical replan after a measured unpinned-framework failure.

    Operator-only: preserves prior blockers, requires native sponsorship and a
    fresh read-only hash/baseline/framework inspection. Never reconstructs Red.
    """
    try:
        import native, handoffs, handoff_runtime, artifact_transport_recovery
    except ImportError:
        from broker import native, handoffs, handoff_runtime, artifact_transport_recovery
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','worker_image'}:
        raise ValueError('exact framework replan identity required')
    for key in ('issue_id','source_task'):
        if str(uuid.UUID(payload[key]))!=payload[key]:raise ValueError('invalid framework identity')
    if payload['worker_image']!=broker.IMAGE:raise ValueError('installed immutable worker required')
    with broker.LOCK:
        with broker.db() as con:
            prior=handoffs.load(con,payload['source_task'])
            if not prior or prior['issue_id']!=payload['issue_id']:raise ValueError('framework incident missing')
            data=json.loads(prior['data'])
            if data.get('framework_replan'):
                if data['framework_replan']['request']!=payload:raise ValueError('framework identity drift')
                return data['framework_replan']
            history=[json.loads(r[0]) for r in con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',(payload['issue_id'],))]
            if any(h.get('framework_replan') for h in history):raise ValueError('framework replan consumed')
            route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            route=json.loads(route_row[0]) if route_row else {}
            if (prior['stage']!='test_first_blocked' or data.get('error')!='test_first_correction_failed_after_cto_diagnosis'
                    or not route.get('enabled') or not route.get('test_first') or route.get('author')==route.get('cto')):
                raise ValueError('blocked independent framework route required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():
                raise ValueError('Red exists; framework replan forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
                raise ValueError('idle workers required')
        diagnostic=json.loads((broker.STATE/'test-first-incidents'/(payload['source_task']+'.json')).read_text())
        if (diagnostic!=data.get('diagnostic') or diagnostic.get('kind')!='rejected_red'
                or diagnostic.get('task_id')!=payload['source_task'] or diagnostic.get('issue_id')!=payload['issue_id']
                or diagnostic.get('exit_code')!=1 or diagnostic.get('command',[None])[1:3]!=['-m','unittest']
                or "ModuleNotFoundError: No module named 'pytest'" not in diagnostic.get('output_excerpt','')
                or set(diagnostic.get('test_sha256',{}))!=set(route['test_first_files'])
                or len(route['test_first_files'])!=1):
            raise ValueError('exact preserved pytest import diagnostic required')
        settings=json.loads((broker.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source.get('id')
                or source.get('status')!='completed' or any(r.get('status') in ('queued','running') for r in runs)):
            raise ValueError('latest idle completed author required')
        sponsors=[h for h in history if h.get('test_first_correction_wakeup')==source.get('wakeup_id')]
        if len(sponsors)!=1:raise ValueError('exact existing CTO sponsorship required')
        sponsor=sponsors[0];cto=next((r for r in runs if r['id']==sponsor.get('cto_task')), {})
        decision=handoff_runtime.Effects(broker,settings).decision(cto)
        if (cto.get('status')!='completed' or cto.get('agent_id')!=route['cto']
                or decision!=sponsor.get('decision') or decision.get('action')!='request_correction'
                or decision.get('optional_files')!=[]):raise ValueError('exact existing CTO sponsorship required')
        proof=artifact_transport_recovery.verify_preserved_failure(broker,source['id'],
            {'files':diagnostic['test_sha256']},failed=False,framework=True)
        if (proof.get('verified') is not True or proof.get('baseline_unchanged') is not True
                or proof.get('framework_mismatch') is not True or proof.get('task_id')!=source['id']):
            raise ValueError('fixed read-only framework experiment required')
        receipt=dict(kind='unpinned_pytest_cto_replan_v1',request=payload,previous_blocker=data.copy(),
            diagnostic_sha256=hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),
            proof=proof,at=time.time(),delivery_approval=False)
        data.update(framework_replan=receipt,error='new_test_framework_mismatch')
        with broker.db() as con:
            handoffs.save(con,source['id'],payload['issue_id'],'technical_decision_required',route['cto'],data,time.time())
        return receipt


def replan_structure(broker, payload):
    """One new CTO incident for measured progress from empty to no methods."""
    try:
        import native, handoffs
    except ImportError:
        from broker import native, handoffs
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'source_task', 'worker_image'}:
        raise ValueError('exact structural replan identity required')
    for key in ('issue_id', 'source_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('invalid structural replan identity')
    if payload['worker_image'] != broker.IMAGE:
        raise ValueError('installed structural recovery image required')
    with broker.LOCK:
        with broker.db() as con:
            prior = handoffs.load(con, payload['source_task'])
            if not prior or prior['issue_id'] != payload['issue_id']:
                raise ValueError('blocked structural incident missing')
            data = json.loads(prior['data'])
            if data.get('structural_replan'):
                if data['structural_replan']['request'] != payload:
                    raise ValueError('structural replan identity drift')
                return data['structural_replan']
            rows = con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',
                               (payload['issue_id'],)).fetchall()
            history = [json.loads(row[0]) for row in rows]
            if any(h.get('structural_replan') for h in history):
                raise ValueError('structural replan already consumed for issue')
            providers = [h for h in history if h.get('provider_recovery')]
            route_row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (payload['issue_id'],)).fetchone()
            route = json.loads(route_row[0]) if route_row else {}
            if (prior['stage'] != 'test_first_blocked' or len(providers) != 1
                    or not route.get('enabled') or not route.get('test_first')
                    or route.get('author') == route.get('cto')):
                raise ValueError('blocked independent structural replan required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?', (payload['issue_id'],)).fetchone():
                raise ValueError('Red exists; structural replan forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
                raise ValueError('structural replan requires idle workers')
        if not broker.test_artifact_phase_context(payload['issue_id'], route['author']):
            raise ValueError('structural artifact gate must be enabled')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        source = next((r for r in authors if r['id'] == payload['source_task']), {})
        if (not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source.get('id')
                or source.get('status') != 'completed'
                or source.get('wakeup_id') != providers[0].get('artifact_recovery_wakeup')
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('exact idle latest provider-repaired author required')
        try:
            broker.capture_test_first_red({'task_id': source['id']})
        except ValueError as error:
            if str(error) != 'test-first NEW test has no executable test methods':
                raise
        else:
            raise ValueError('valid Red exists; structural replan forbidden')
        diagnostic = json.loads((broker.STATE / 'test-first-incidents' / (source['id'] + '.json')).read_text())
        files = diagnostic.get('files', {})
        if (diagnostic.get('issue_id') != payload['issue_id'] or diagnostic.get('task_id') != source['id']
                or diagnostic.get('kind') != 'rejected_snapshot' or diagnostic.get('category') != 'new_test_no_methods'
                or set(files) != set(route.get('test_first_files', [])) or len(files) != 1
                or any(type(f.get('bytes')) is not int or not 0 < f['bytes'] <= 32768
                       or not re.fullmatch(r'[0-9a-f]{64}', str(f.get('sha256', ''))) for f in files.values())):
            raise ValueError('exact nonempty no-methods snapshot required')
        receipt = {'request': payload, 'at': time.time(), 'previous_blocker': data.copy(),
                   'diagnostic_sha256': hashlib.sha256(json.dumps(diagnostic, sort_keys=True).encode()).hexdigest(),
                   'kind': 'nonempty_no_methods_cto_replan_v1'}
        data.update(structural_replan=receipt, diagnostic=diagnostic,
                    error='test-first NEW test has no executable test methods')
        with broker.db() as con:
            handoffs.save(con, source['id'], payload['issue_id'], 'technical_decision_required',
                          route['cto'], data, time.time())
        return receipt
