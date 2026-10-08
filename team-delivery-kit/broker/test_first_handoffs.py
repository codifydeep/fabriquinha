"""Durable tests-only → controller Red → implementation handoff."""
import hashlib
import json
import re
import time
import uuid

try:
    import handoffs
except ImportError:
    from broker import handoffs


def resume_diagnosis(broker, payload):
    """Replay one evidence-missing CTO diagnosis after a fixed offline probe."""
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'source_task', 'cto_task'}:
        raise ValueError('exact blocked diagnostic identity required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid diagnostic identity')
    try:
        import native
    except ImportError:
        from broker import native
    with broker.LOCK:
        with broker.db() as con:
            prior = handoffs.load(con, payload['source_task'])
            route_row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                    (payload['issue_id'],)).fetchone()
            if not prior or prior['issue_id'] != payload['issue_id'] or not route_row:
                raise ValueError('blocked diagnostic missing')
            route, data = json.loads(route_row[0]), json.loads(prior['data'])
            if data.get('diagnostic_retry'):
                if data.get('previous_cto_diagnosis', {}).get('cto_task') != payload['cto_task']:
                    raise ValueError('diagnostic replay identity drift')
                return {'resumed': True, 'issue_id': payload['issue_id'],
                        'manifest_sha256': data['diagnostic'].get('manifest_sha256'),
                        'diagnostic_sha256': hashlib.sha256(json.dumps(data['diagnostic'], sort_keys=True).encode()).hexdigest()}
            if (prior['stage'] != 'test_first_blocked'
                    or data.get('error') != 'test_first_cto_requires_replanning'
                    or data.get('cto_task') != payload['cto_task']
                    or data.get('phase') != 'test_first' or data.get('diagnostic')
                    or data.get('decision', {}).get('action') != 'escalate_cto'
                    or not route.get('test_first') or not route.get('enabled')):
                raise ValueError('only evidence-missing CTO diagnosis may resume')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',
                           (payload['issue_id'],)).fetchone():
                raise ValueError('Red already exists; diagnostic replay forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
                raise ValueError('diagnostic repair requires idle workers')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        source = next((r for r in runs if r['id'] == payload['source_task']), None)
        cto = next((r for r in runs if r['id'] == payload['cto_task']), None)
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        if (not source or source.get('agent_id') != route['author'] or source.get('status') != 'completed'
                or not cto or cto.get('agent_id') != route['cto'] or cto.get('status') != 'completed'
                or cto.get('wakeup_id') != data.get('test_first_cto_wakeup')
                or any(r.get('status') in ('queued', 'running') for r in runs)
                or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source['id']):
            raise ValueError('exact idle source and independent CTO required')
        # Fixed offline rerun of the preserved snapshot; no agent command is accepted.
        try:
            broker.capture_test_first_red({'task_id': source['id']})
        except ValueError:
            pass
        else:
            raise ValueError('snapshot now has valid Red; diagnosis replay forbidden')
        diagnostic = json.loads((broker.STATE / 'test-first-incidents' /
                                 (source['id'] + '.json')).read_text())
        empty_files = diagnostic.get('files', {})
        empty_snapshot = (diagnostic.get('kind') == 'rejected_snapshot'
            and diagnostic.get('category') == 'empty_new_test'
            and isinstance(empty_files, dict) and bool(empty_files)
            and all(isinstance(f, dict) and f.get('bytes') == 0
                and f.get('sha256') == hashlib.sha256(b'').hexdigest()
                for f in empty_files.values()))
        green_rejection = diagnostic.get('kind') == 'rejected_red' and diagnostic.get('exit_code') == 0
        if (diagnostic.get('issue_id') != payload['issue_id']
                or diagnostic.get('task_id') != source['id']
                or not (empty_snapshot or green_rejection)):
            raise ValueError('executed all-Green or proven empty-test rejection evidence required')
        data['previous_cto_diagnosis'] = {k: data.get(k) for k in
                                         ('cto_task', 'decision', 'error', 'test_first_cto_wakeup')}
        data.update(diagnostic_retry=1, diagnostic=diagnostic,
                    error=('ValueError:test-first NEW test is empty' if empty_snapshot
                           else 'ValueError:Red must be an executed failing test suite'))
        for key in ('cto_task', 'decision', 'test_first_cto_wakeup', 'dispatched_at'):
            data.pop(key, None)
        with broker.db() as con:
            handoffs.save(con, source['id'], payload['issue_id'], 'technical_decision_required',
                          route['cto'], data, time.time())
        return {'resumed': True, 'issue_id': payload['issue_id'],
                'manifest_sha256': diagnostic.get('manifest_sha256'),
                'diagnostic_sha256': hashlib.sha256(json.dumps(diagnostic, sort_keys=True).encode()).hexdigest()}


def technical_recovery(broker, route, runs, source, prior, effects):
    """One actual CTO diagnosis and one author correction; never a passive wait."""
    data = json.loads(prior['data'])
    try:import calibration_failure_plan
    except ImportError:from broker import calibration_failure_plan
    if calibration_failure_plan.handle(broker,route,runs,source,prior,effects):return
    try:import calibration_rework
    except ImportError:from broker import calibration_rework
    if calibration_rework.handle(broker,route,runs,source,prior,effects):return
    issue, key, now = route['issue_id'], source['id'], time.time()
    def save(stage, owner):
        with broker.db() as con:
            handoffs.save(con, key, issue, stage, owner, data, now)
    def block(reason):
        if data.get('error') and data.get('error') != reason:
            data.setdefault('blocked_cause', data['error'])
        data['error'] = reason
        data['required_action'] = 'inspect_recorded_test_first_incident_and_replan'
        save('test_first_blocked', route['cto'])
    if prior['stage']=='test_first_selected_read_recovery_pending':
        repair=data['selected_read_recovery']
        if not effects.implementation_available(issue,route['author']):return
        marker=hashlib.sha256((issue+':'+key+':controller-selected-read-recovery-v1').encode()).hexdigest()
        instruction=('CONTROLLER CHANGED SELECTED-READ CONTRACT. Existing independent CTO instruction: '
            +repair['decision']['reason']+'. The previous read_file arguments were rejected before any '
            'tool ran. The controller now supplies ONLY exact selected read requests; actual tool '
            'results remain mandatory and are not fabricated. Resume tests-only in the same workspace; '
            'write only the declared NEW test, preserve all baseline/product files and run the full '
            'pinned suite. Red and independent test review are required before implementation. '
            'This is one changed-condition attempt, not a budget reset or delivery approval.')
        wake=effects.ensure_wakeup(issue,route['author'],repair['request']['cto_task'],marker,instruction,
            allow_create=effects.remaining_calls()>=route['minimum_calls'])
        if wake:
            data.update(selected_read_wakeup=wake['id'],selected_read_dispatched_at=now)
            save('test_first_selected_read_recovery_wait',route['author'])
        return
    if prior['stage']=='test_first_selected_read_recovery_wait':
        if now-data['selected_read_dispatched_at']>=1800:block('selected_read_recovery_not_started')
        return
    if prior['stage']=='test_first_surgical_recovery_pending':
        if not effects.implementation_available(issue,route['author']):return
        config=data['surgical_recovery']
        typed=config.get('protocol')=='typed_v2'
        marker=hashlib.sha256((issue+':'+key+(':surgical-test-once-v2' if typed else ':surgical-test-once-v1')).encode()).hexdigest()
        instruction=('CONTROLLER SPONSORED SURGICAL TEST ADAPTATION. The previous full-file response failed before writing. '
            'Use the new hash-checked write_file JSON-envelope operation after reading the whole existing NEW test. '
            'Adapt pytest imports/scaffolding and wrap the same test in unittest.TestCase with self. '
            'Preserve the complete original test body and assertions, no product edits or test skipping. '
            'Terminal and patch tools are disabled. Controller executes full-suite Red; this is not approval. '
            'One changed-contract attempt only. The current test hash is '+config['expected_sha256']+'.')
        if typed:instruction=instruction.replace('write_file JSON-envelope operation',
            'surgical_test_edit operation with explicit path, expected_sha256 and edits arguments')
        if config.get('feedback_request'):
            instruction+=' Previously rejected: unittest_discovery_required and test_methods_missing. '
            instruction+='Use a top-level class extending unittest.TestCase and retain each original test_name as a method with self. '
            instruction+='Indent the unchanged complete method body inside that class; do not delete, rename or replace tests. '
            instruction+='Handler errors now include an exact category and next_operation. Correct only that cause, within two edit attempts.'
        wake=effects.ensure_wakeup(issue,route['author'],key,marker,instruction,
            allow_create=effects.remaining_calls()>=route['minimum_calls'])
        if wake:
            data.update(surgical_wakeup=wake['id'],surgical_dispatched_at=now)
            save('test_first_surgical_recovery_wait',route['author'])
        return
    if prior['stage']=='test_first_surgical_recovery_wait':
        if now-data['surgical_dispatched_at']>=1800:block('surgical_correction_not_started')
        return
    if prior['stage'] in ('test_first_artifact_recovery_pending', 'test_first_provider_recovery_pending',
                          'test_first_transport_recovery_pending', 'test_first_integration_recovery_pending'):
        provider_repair = prior['stage'] == 'test_first_provider_recovery_pending'
        integration_repair = prior['stage'] == 'test_first_integration_recovery_pending'
        transport_repair = prior['stage'] == 'test_first_transport_recovery_pending'
        repair = data['integration_recovery'] if integration_repair else data['transport_recovery'] if transport_repair else (data['provider_recovery'] if provider_repair else data['artifact_recovery'])
        if not effects.implementation_available(issue, route['author']):
            return
        marker = hashlib.sha256((issue + ':' + key + (':' + repair['repair_kind'] if integration_repair else ':qualified-acp-response-enforcement-v1' if transport_repair else ':provider-pre-tool-recovery-v1' if provider_repair
                                else ':artifact-gate-recovery-v1')).encode()).hexdigest()
        instruction = ('CONTROLLER CHANGED TEST-ARTIFACT CONTRACT. Existing CTO instruction: '
            + repair['decision']['reason'] + '. Follow the selected read_file pages, then '
            'produce the complete NEW test with the actual write_file tool. A textual '
            'claim does not count as a write. Preserve all baseline files. Run the full '
            'pinned suite after writing. Controller Red and independent immutable review '
            'remain mandatory before product implementation. This is one changed-contract '
            'attempt, not a retry-budget reset or delivery approval.')
        if integration_repair and repair['repair_kind'] == 'post_read_compact_write_replan_v1':
            instruction += (' MEASURED WRITE FAILURE: prior response reached its output budget and '
                'was rejected; truncation is not proven. Change execution granularity: first '
                'write one compact executable unittest.TestCase with a real failing-behavior '
                'assertion, aiming below4000 characters and never above6144 characters. '
                'Then extend the SAME new test incrementally to cover ALL unchanged acceptance '
                'criteria. Do not copy the product or build a giant replacement harness. '
                'The first small test is NOT completion. Preserve full-suite Red evidence, '
                'independent review and the existing final artifact size gate.')
        wakeup = effects.ensure_wakeup(issue, route['author'], key, marker, instruction,
                                      allow_create=effects.remaining_calls() >= route['minimum_calls'])
        if wakeup is not None:
            data.update(artifact_recovery_wakeup=wakeup['id'], artifact_dispatched_at=now)
            save('test_first_integration_recovery_wait' if integration_repair else 'test_first_transport_recovery_wait' if transport_repair else 'test_first_provider_recovery_wait' if provider_repair else 'test_first_artifact_recovery_wait', route['author'])
        return
    if prior['stage'] in ('test_first_artifact_recovery_wait', 'test_first_provider_recovery_wait',
                          'test_first_transport_recovery_wait', 'test_first_integration_recovery_wait'):
        if now - data['artifact_dispatched_at'] >= 1800:
            block('artifact_recovery_not_started')
        return
    if prior['stage'] == 'test_first_bootstrap_recovery_pending':
        repair=data['bootstrap_recovery']
        if not effects.implementation_available(issue,route['author']):return
        marker=hashlib.sha256((issue+':'+key+':bootstrap-repair-once').encode()).hexdigest()
        instruction=('CONTROLLER PROVEN BOOTSTRAP REPAIR. The fixed offline seed and '
            'permission fence passed on the exact preserved workspace. Resume the original '
            'CTO-sponsored tests-only correction: '+repair['reason']+
            '. Edit only the declared NEW test; preserve product code and all old tests. '
            'Keep all methods/assertions/acceptance coverage and reduce the NEW test to '
            '<=32768 UTF-8 bytes. Run the full pinned suite. No implementation permission '
            'until new controller Red and independent immutable review. No retry budget reset.')
        if repair.get('normalization'):
            instruction=('CONTROLLER AST-PRESERVING NORMALIZATION VERIFIED. '+repair['reason']+
                ' The current file already satisfies the size gate. Read it, run the exact '
                'full pinned suite and finish with factual evidence. No formatting or '
                'further code changes are needed for size. Do not modify existing tests.')
        wakeup=effects.ensure_wakeup(issue,route['author'],key,marker,instruction,
            allow_create=effects.remaining_calls()>=route['minimum_calls'])
        if wakeup is None:return
        data.update(bootstrap_recovery_wakeup=wakeup['id'],bootstrap_dispatched_at=now)
        save('test_first_bootstrap_recovery_wait',route['author'])
        return
    if prior['stage'] == 'test_first_bootstrap_recovery_wait':
        if now-data['bootstrap_dispatched_at']>=1800:block('bootstrap_repair_not_started')
        return
    if prior['stage'] == 'test_first_blocked':
        if (data.get('error')=='test_first_cto_requires_replanning'
                and data.get('decision',{}).get('action')=='escalate_cto'
                and not data.get('constraint_presentation_replay')):
            certificate=getattr(effects,'constraint_presentation',lambda *_:None)(issue,key)
            if certificate:
                data['constraint_presentation_replay']=dict(certificate=certificate,
                    previous_decision=data.get('decision'),author_retry_authorized=False,delivery_approval=False)
                for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):data.pop(field,None)
                data['error']='measured_constraint_presentation_requires_independent_decision'
                save('technical_decision_required',route['cto'])
                return
        if (data.get('error')=='test_first_cto_requires_replanning'
                and data.get('decision',{}).get('action')=='escalate_cto'
                and not data.get('prospective_capacity_replay')):
            certificate=getattr(effects,'prospective_capacity',lambda *_:None)(issue,key)
            if certificate:
                data['prospective_capacity_replay']=dict(certificate=certificate,
                    previous_cto_task=data.get('cto_task'),previous_decision=data.get('decision'),
                    author_retry_authorized=False,delivery_approval=False)
                for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):data.pop(field,None)
                data['error']='prospective_capacity_experiment_requires_independent_decision'
                save('technical_decision_required',route['cto'])
                return
        if not data.get('diagnostic'):
            diagnostic = effects.test_first_failure(issue, key)
            if diagnostic:
                data['diagnostic'] = diagnostic
                save('test_first_blocked', route['cto'])
        diagnostic=data.get('diagnostic') or {}
        if (data.get('error')=='test_first_correction_failed_after_cto_diagnosis'
                and not data.get('verified_tool_incident')):
            receipt=getattr(effects,'verified_tool_incident',lambda *_:None)(issue,key)
            if receipt:
                data.update(verified_tool_incident=receipt,error='verified_new_tool_incident_requires_cto')
                save('technical_decision_required',route['cto'])
                return
        if (data.get('error')=='test_first_cto_requires_replanning'
                and data.get('unchanged_seed_diagnosis_replay') and not data.get('transport_qualification_replay')
                and data.get('decision',{}).get('action')=='escalate_cto'):
            certificate=getattr(effects,'transport_qualification',lambda *_:None)(issue,key)
            if certificate:
                data['transport_qualification_replay']=dict(certificate=certificate,
                    previous_cto_task=data.get('cto_task'),previous_decision=data.get('decision'),
                    author_retry_authorized=False,delivery_approval=False)
                for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):data.pop(field,None)
                data['error']='qualified_changed_transport_requires_independent_decision'
                save('technical_decision_required',route['cto'])
                return
        if (data.get('error')=='test_first_cto_execution_failed'
                and diagnostic and not data.get('decision_format_retry')
                and not data.get('pre_red_format_checked')):
            candidates=[r for r in runs if r.get('wakeup_id')==data.get('test_first_cto_wakeup')
                and r.get('agent_id')==route['cto'] and r.get('status')=='failed']
            if len(candidates)!=1:return
            recipient=candidates[0]
            rejection=effects.pre_red_format_rejection(route,recipient)
            data['pre_red_format_checked']=recipient['id']
            if (rejection.get('operation')=='rejected_typed_decision_adapter_v1'
                    and rejection.get('category')=='typed_schema_maxLength'
                    and rejection.get('delivery_approval') is False
                    and rejection.get('worker_tool_executed') is False
                    and re.fullmatch(r'[a-f0-9]{64}',rejection.get('upstream_sha256',''))):
                data['previous_invalid_decision']={
                    'cto_task':recipient['id'],'wakeup':data['test_first_cto_wakeup'],
                    'rejection':rejection,'verdict_replayed':False,'delivery_approval':False}
                data.update(decision_format_retry=1,error='technical_reason_exceeds_limit')
                for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):
                    data.pop(field,None)
                save('technical_decision_required',route['cto'])
            else:save('test_first_blocked',route['cto'])
            return
        if (data.get('error')=='test_first_cto_requires_replanning'
                and not data.get('artifact_diagnosis_replay')
                and data.get('decision',{}).get('action')=='escalate_cto'
                and diagnostic.get('kind')=='rejected_test_write'
                and diagnostic.get('operation')=='rejected_test_write_v1'
                and diagnostic.get('category')=='artifact_test_methods_missing'
                and diagnostic.get('issue_id')==issue and diagnostic.get('task_id')==key
                and diagnostic.get('write_executed') is False
                and diagnostic.get('tests_executed') is False
                and diagnostic.get('red_verified') is False
                and diagnostic.get('delivery_approval') is False):
            data['artifact_diagnosis_replay']={
                'previous_cto_task':data.get('cto_task'),'previous_decision':data.get('decision'),
                'diagnostic_sha256':hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),
                'author_retry_authorized':False,'delivery_approval':False}
            for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):
                data.pop(field,None)
            data['error']='proxy_rejected_test_methods_missing'
            save('technical_decision_required',route['cto'])
            return
        if (data.get('error')=='test_first_cto_requires_replanning'
                and not data.get('forced_tool_diagnosis_replay')
                and data.get('decision',{}).get('action')=='escalate_cto'
                and diagnostic.get('kind')=='rejected_forced_tool_response'
                and diagnostic.get('operation')=='rejected_forced_tool_response_v1'
                and diagnostic.get('tool')=='patch'
                and diagnostic.get('category')=='incomplete_forced_tool_response'
                and diagnostic.get('issue_id')==issue and diagnostic.get('task_id')==key
                and all(diagnostic.get(k) is False for k in
                    ('write_executed','tests_executed','red_verified','delivery_approval'))):
            data['forced_tool_diagnosis_replay']=dict(previous_cto_task=data.get('cto_task'),
                previous_decision=data.get('decision'),
                diagnostic_sha256=hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),
                author_retry_authorized=False,delivery_approval=False)
            for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):data.pop(field,None)
            data['error']='proxy_rejected_forced_patch_response'
            save('technical_decision_required',route['cto'])
            return
        if (data.get('error')=='test_first_cto_requires_replanning'
                and not data.get('unchanged_seed_diagnosis_replay')
                and data.get('decision',{}).get('action')=='escalate_cto'
                and diagnostic.get('kind')=='unchanged_seed_read_only_failure'
                and diagnostic.get('operation')=='unchanged_seed_read_only_failure_v1'
                and diagnostic.get('issue_id')==issue and diagnostic.get('task_id')==key
                and all(diagnostic.get(k) is False for k in
                    ('proxy_failure_cause_proven','write_executed','tests_executed','red_verified','delivery_approval'))):
            data['unchanged_seed_diagnosis_replay']=dict(previous_cto_task=data.get('cto_task'),
                previous_decision=data.get('decision'),
                diagnostic_sha256=hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),
                author_retry_authorized=False,delivery_approval=False)
            for field in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):data.pop(field,None)
            data['error']='unchanged_seed_after_read_only_failure'
            save('technical_decision_required',route['cto'])
            return
        # One changed, explicitly bounded output contract, never a blind author
        # retry or reinterpretation of the rejected technical decision.
        if (data.get('error') == 'test_first_cto_invalid_decision:ValueError'
                and not data.get('decision_format_retry') and data.get('diagnostic')):
            candidates = [r for r in runs if r.get('wakeup_id') == data.get('test_first_cto_wakeup')
                          and r.get('agent_id') == route['cto'] and r.get('status') == 'completed']
            if len(candidates) != 1:
                return
            recipient = candidates[0]
            output = (recipient.get('result') or {}).get('output')
            if not isinstance(output, str) or len(output.strip()) > 5000:
                return
            text = output.strip()
            fenced = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.I | re.S)
            try:
                decision = json.loads(fenced.group(1) if fenced else text)
            except ValueError:
                return
            if (not isinstance(decision, dict) or set(decision) != {'action', 'reason', 'optional_files'}
                    or decision.get('action') not in ('request_correction', 'escalate_cto')
                    or decision.get('optional_files') != []
                    or not isinstance(decision.get('reason'), str)
                    or not 3000 < len(decision['reason']) <= 5000):
                return
            data['previous_invalid_decision'] = {
                'cto_task': recipient['id'], 'wakeup': data['test_first_cto_wakeup'],
                'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
                'reason_characters': len(decision['reason']), 'action': decision['action']}
            data.update(decision_format_retry=1, error='technical_reason_exceeds_limit')
            for field in ('cto_task', 'decision', 'test_first_cto_wakeup', 'dispatched_at'):
                data.pop(field, None)
            save('technical_decision_required', route['cto'])
        return
    if prior['stage'] == 'technical_decision_required':
        with broker.db() as con:
            used = con.execute("SELECT data FROM delivery_handoffs WHERE issue_id=? AND source_task<>?",
                               (issue, key)).fetchall()
        structural = data.get('structural_replan') or {}
        diagnostic = data.get('diagnostic') or {}
        qualified_structure = (structural.get('kind') == 'nonempty_no_methods_cto_replan_v1'
            and structural.get('request', {}).get('issue_id') == issue
            and structural.get('request', {}).get('source_task') == key
            and diagnostic.get('category') == 'new_test_no_methods'
            and structural.get('diagnostic_sha256') == hashlib.sha256(
                json.dumps(diagnostic, sort_keys=True).encode()).hexdigest())
        framework=data.get('framework_replan') or {}
        try:import pre_red_infra_replan
        except ImportError:from broker import pre_red_infra_replan
        with broker.db() as con:
            qualified_infrastructure=pre_red_infra_replan.qualified(con,issue,key,data)
        try:import host_restart_recovery
        except ImportError:from broker import host_restart_recovery
        with broker.db() as con:
            qualified_restart=host_restart_recovery.qualified(con,issue,key,data)
        try:import postwrite_diagnosis
        except ImportError:from broker import postwrite_diagnosis
        with broker.db() as con:
            qualified_postwrite=postwrite_diagnosis.qualified(con,issue,key,data)
        try:import read_capacity_diagnosis
        except ImportError:from broker import read_capacity_diagnosis
        with broker.db() as con:
            qualified_capacity=read_capacity_diagnosis.qualified(con,issue,key,data)
        try:import seeded_byte_budget_replan
        except ImportError:from broker import seeded_byte_budget_replan
        with broker.db() as con:
            qualified_byte_budget=seeded_byte_budget_replan.qualified(con,issue,key,data)
        try:import transport_qualification
        except ImportError:from broker import transport_qualification
        with broker.db() as con:
            qualified_transport=transport_qualification.qualified(con,issue,key,data,getattr(broker,'IMAGE',None))
        try:import verified_tool_incident
        except ImportError:from broker import verified_tool_incident
        with broker.db() as con:
            qualified_tool_incident=verified_tool_incident.qualified(con,issue,key,data)
            qualified_constraint_presentation=verified_tool_incident.presentation_qualified(con,issue,key,data)
        try:import prospective_capacity
        except ImportError:from broker import prospective_capacity
        with broker.db() as con:
            qualified_prospective_capacity=prospective_capacity.qualified(con,issue,key,data)
        qualified_framework=(framework.get('kind')=='unpinned_pytest_cto_replan_v1'
            and framework.get('request',{}).get('issue_id')==issue
            and framework.get('request',{}).get('source_task')==key
            and framework.get('proof',{}).get('verified') is True
            and framework.get('proof',{}).get('framework_mismatch') is True
            and framework.get('diagnostic_sha256')==hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest())
        if any(json.loads(row['data']).get('test_first_cto_wakeup') for row in used) and not (qualified_structure or qualified_framework or qualified_infrastructure or qualified_restart or qualified_postwrite or qualified_capacity or qualified_byte_budget or qualified_transport or qualified_tool_incident or qualified_prospective_capacity):
            block('test_first_correction_failed_after_cto_diagnosis')
            return
        suffix = ':diagnostic-replay-1' if data.get('diagnostic_retry') else ''
        if qualified_byte_budget:suffix+=':preserved-seed-byte-budget-v1'
        if qualified_tool_incident:suffix+=':verified-tool-incident-v1:'+data['verified_tool_incident']['fingerprint']
        if qualified_constraint_presentation:suffix+=':measured-constraint-presentation-v1'
        if qualified_prospective_capacity:suffix+=':prospective-capacity-v1:'+data['prospective_capacity_replay']['certificate']['probe_sha256']
        if data.get('artifact_diagnosis_replay'):
            suffix+=':proxy-artifact-evidence-v1'
        if data.get('forced_tool_diagnosis_replay'):
            suffix+=':proxy-forced-patch-evidence-v1'
        if data.get('unchanged_seed_diagnosis_replay'):
            suffix+=':unchanged-seed-read-only-evidence-v1'
        if qualified_transport:
            suffix+=':qualified-transport-v1:'+data['transport_qualification_replay']['certificate']['config_sha256']
        if qualified_structure:
            suffix += ':nonempty-no-methods-replan-v1'
        if qualified_framework:
            suffix += ':unpinned-pytest-replan-v1'
        if qualified_infrastructure:
            suffix += ':preserved-pretool-infrastructure-v1'
        if qualified_restart:
            suffix += ':verified-host-restart-v1'
        if qualified_capacity:
            suffix += ':verified-read-capacity-v1'
        if data.get('decision_format_retry'):
            suffix += ':bounded-format-1'
        if data.get('fenced_patch_diagnosis'):
            try:import fenced_patch_diagnosis
            except ImportError:from broker import fenced_patch_diagnosis
            with broker.db() as con:
                if not fenced_patch_diagnosis.qualified(con,issue,key,data):
                    raise ValueError('registered exact fenced-write diagnosis required')
            suffix += ':measured-fenced-write-v1'
        marker = hashlib.sha256((issue + ':' + key + ':test-first-cto' + suffix).encode()).hexdigest()
        technical_evidence=diagnostic_presentation(data)
        if qualified_prospective_capacity:
            technical_evidence=dict(source_task=key,qualification=data['prospective_capacity_replay']['certificate'],
                historical_native_argument_constraint='UNKNOWN')
        if qualified_transport:
            technical_evidence=dict(source_task=key,manifest_sha256=diagnostic.get('manifest_sha256'),
                qualification=data['transport_qualification_replay']['certificate'])
        if qualified_restart:
            technical_evidence=dict(source_task=key, diagnostic=diagnostic,
                proof=data['host_restart_recovery']['proof'],
                author_retry_authorized=False, delivery_approval=False)
        if qualified_infrastructure:
            technical_evidence=dict(source_task=key,diagnostic=diagnostic,
                proof=data['infrastructure_replan']['proof'],
                prior_decision_task=data['infrastructure_replan']['request']['cto_task'])
        if qualified_framework:
            # Durable previous_blocker may contain the whole historical chain.
            # Keep it in storage, never serialize it recursively into a wakeup.
            technical_evidence={
                'source_task':key,'error':data['error'],
                'diagnostic':{k:diagnostic.get(k) for k in
                    ('kind','task_id','issue_id','exit_code','command','manifest_sha256','test_sha256','output_sha256')},
                'experiment':{k:framework['proof'].get(k) for k in
                    ('verified','baseline_unchanged','framework_mismatch','manifest_sha256')},
                'diagnostic_sha256':framework['diagnostic_sha256']}
        instruction = (
            'CONTROLLER TEST-FIRST TECHNICAL INCIDENT. No Red receipt exists. '
            'Diagnose the failed tests-only execution; product code and all existing '
            'tests must remain unchanged. Evidence: ' + json.dumps(technical_evidence, sort_keys=True)
            + '. Do not infer a stale lease, file defect or successful execution '
            'without evidence. '+('The historical upstream cause remains UNKNOWN. New installed safeguards have '
            'passed native and integrated offline ACP negative/positive controls on the current worker. '
            'You may prescribe ONE concrete bounded tests-only experiment based on these changed conditions, '
            'or escalate with a specific missing evidence requirement. Do not claim the old cause is proven '
            'or replay an identical instruction. Inspect the preserved NEW test; use a narrow patch that '
            'retains quoted string values and all assertions. Syntax-valid Python alone does not validate '
            'embedded JavaScript: controller harness calibration, behavioral Red and independent review '
            'remain mandatory. No retry budget/depth reset or product permission. '
            if qualified_transport else 'The frozen prospective experiment measured artifact_size rejection, '
            'not the historical native cause. You may prescribe ONE concrete tests-only changed-precondition '
            'capacity recovery: reduce COMMENT-only overhead before additions, preserving Python/JavaScript '
            'semantics, every assertion, discovery and acceptance coverage. No file limit increase, '
            'no test removal, no skip, no product edit or depth reset. If safe compaction cannot be established, '
            'escalate with the specific missing evidence. Calibration, behavioral Red and independent review '
            'remain mandatory. Do not claim the original invalid argument cause is known. '
            if qualified_prospective_capacity else 'If the failure lacks a concrete cause, escalate '
            'for controller diagnostics rather than prescribing an identical retry. ')+
            'Return only JSON with action (request_correction or escalate_cto), reason '
            'and optional_files ([]). request_correction must give the original author '
            'a concrete tests-only recovery action. Do not change files or weaken TDD.'
            + ('\nPROXY ARTIFACT REJECTION: the write was rejected before execution because '
               'the generated Python file lacked test_ methods. No suite ran; no unittest '
               'traceback or Red exists. Prescribe actual unittest.TestCase test_ methods '
               'with real Handler assertions and all unchanged acceptance coverage. '
               'Only the new test may be corrected; inspect the workspace before writing. '
               'Do not disable the gate or treat this as an OpenRouter outage.'
               if diagnostic.get('kind')=='rejected_test_write' else '')
            + ('\nPROXY PATCH RESPONSE REJECTION: the exact owned proxy refused the forced tool response '
               'BEFORE forwarding that response to the worker. Earlier reads may have executed. '
               'No Red or successful patch follows from this receipt. A legacy receipt without shape counts does '
               'not prove truncation, multiple calls or a provider outage. The changed proxy can make ONE format '
               'correction only for a newly measured complete response containing multiple pinned patch calls; '
               'it forwards none of the rejected calls, then revalidates every original gate. '
               'Decide whether a concrete tests-only correction is warranted, or name the remaining diagnostic. '
               'Never disable the gate, approve Red or ask the CEO to decide a technical issue.'
               if diagnostic.get('kind')=='rejected_forced_tool_response'
               and not verified_tool_incident.measured_fact(diagnostic) else '')
            + ('\nNEW VALIDATOR INCIDENT: read the category and constraint from the controller receipt; '
               'invalid_forced_argument is NOT an incomplete stream or provider outage. A missing constraint '
               'means the specific cause remains UNKNOWN: return escalate_cto with the exact evidence or '
               'bounded diagnostic experiment required, not request_correction. The controller will reject '
               'author retry for an unknown constraint. A measured constraint permits only a concrete '
               'tests-only remedy via your independent decision; it never waives calibration, Red or review. '
               'Identical constraints under new task/call IDs do not rearm diagnosis; size counts alone '
               'are not changed evidence. No technical escalation to the CEO.'
               if qualified_tool_incident and not qualified_prospective_capacity
               and not verified_tool_incident.measured_fact(diagnostic) else '')
            + ('\nMEASURED ARGUMENT CONSTRAINT (controller fact, NOT missing): '
               +json.dumps(verified_tool_incident.measured_fact(diagnostic),sort_keys=True)+'. '
               'Use the explicit field, constraint and meaning above. Do not describe an existing '
               'constraint as UNKNOWN or request raw model payloads to discover it. This fact only '
               'explains this exact rejected response, not older failures. Decide one concrete '
               'tests-only remedy or escalate with a genuinely different missing requirement. '
               'No identical retry, file-limit increase, skipped tests, automatic Red or delivery '
               'approval. Preserve every assertion and all product/baseline files. '
               if qualified_tool_incident and not qualified_prospective_capacity
               and verified_tool_incident.measured_fact(diagnostic) else '')
            + ('\nUNCHANGED SEED INSPECTION: a NEW fixed offline job verified the entire failed snapshot against '
               'the approved seed manifest, not merely the test hash. All bytes remain unchanged and the actual '
               'native tool history contains only paired read_file calls. The author executed no patch or suite; no Red receipt exists. '
               'This proves preserved state, NOT the lost upstream response shape or provider root cause. '
               'The proxy now measures forced-response shape and permits only one unforwarded format correction '
               'when multiple complete pinned patches are measured. Decide whether ONE concrete tests-only '
               'correction is appropriate: inspect the unchanged harness and use one narrow patch call at a time, '
               'preserving every assertion and behavior. Name additional evidence if insufficient. '
               'Do not replay an identical instruction, waive calibration/Red/review, reset depth or approve delivery.'
               if diagnostic.get('kind')=='unchanged_seed_read_only_failure' and not qualified_transport else '')
            +
            '\nOutput reason in one complete sentence, aim below 900 characters; '
            '1200 characters is the output-contract maximum. Target420characters on format recovery. No preface or Markdown. '
            'This is a routing decision, not proof of delivery or release approval.'
            + ('\nHOST RESTART DIAGNOSIS: an author failed during a daemon restart; '
               'the immediately following author failed before broker admission. '
               'Infrastructure is now reachable and the original workspace is preserved. '
               'All baseline bytes match; no tools were accepted and no Red exists. '
               'Do not infer whether the new test is complete or valid from its hash. '
               'Decide whether ONE tests-only recovery is appropriate. The original '
               'author must inspect the preserved new test and run the full pinned suite. '
               'Product edits, test weakening and replaying identical recovery are forbidden.'
               if qualified_restart else '')
            + ('\nGENERATED CONTEXT REPLAN: the broker rejected the description at native_prompt_bounds '
               'BEFORE model/tool execution. The known controller policy presentation now fits4000, '
               'with original brief/acceptance/CTO unchanged and hashes retained. The workspace '
               'is preserved; baseline bytes match, NEW test is empty, and no Red exists. '
               'Do not infer suspension, stale leases, test failure or an author defect. Decide '
               'whether ONE tests-only recovery after this verified context repair is appropriate; '
               'no product permission, waived gate or CEO technical decision.'
               if qualified_infrastructure and diagnostic.get('category')=='native_prompt_bounds' else
               '\nINFRASTRUCTURE REPLAN: the controller preserved and verified ALL baseline bytes; '
               'the NEW test is empty and zero tools were accepted. Prior author leases expired. '
               'There is no artifact defect proven and no Red. Host suspension coincided with execution; '
               'a bounded AC-only system-sleep guard has been qualified by the operator. '
               'This does not prove the complete cause or successful recovery. Decide whether one '
               'tests-only recovery under the changed host preconditions is appropriate, or specify '
               'the additional diagnostic strictly needed. Do not weaken gates or request CEO technical decisions.'
               if qualified_infrastructure else '')
            + ('\nNEW MEASURED CAUSE: a nonempty Python artifact contains zero test_ methods. '
               'Plan executable unittest.TestCase test_ methods with real assertions and '
               'coverage of the unchanged acceptance criteria. A helper, prose or harness '
               'alone is not a suite. The new structural gate requires actual test methods '
               'before completion. Do not claim to have inspected contents from a hash. '
               'Give a concrete correction, not an identical generic retry.' if qualified_structure else '')
            + ('\nNEW MEASURED CAUSE: pytest import fails under the fixed unittest runner. '
               'Read-only snapshot inspection confirms the same test hash and unchanged baseline. '
               'Sponsor adaptation of the NEW test to unittest.TestCase; preserve all assertions '
               'and acceptance coverage. Replace pytest fixtures/decorators with equivalent stdlib '
               'setup/context managers. Do not merely delete coverage, install pytest, change the '
               'runner or edit product code. A collection/import failure is not behavioral Red. '
               'This changed-contract replan is allowed once; another failure remains blocked.' if qualified_framework else '')
            + '\nDELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n')
        wakeup = effects.ensure_wakeup(issue, route['cto'], key, marker, instruction,
                                      allow_create=effects.remaining_calls() >= route['minimum_calls'])
        if wakeup is None:
            save('technical_decision_required', 'budget')
            return
        data.update(test_first_cto_wakeup=wakeup['id'], dispatched_at=now)
        save('test_first_cto_diagnosis', route['cto'])
        return
    if prior['stage'] == 'test_first_cto_diagnosis':
        candidates = [run for run in runs if run.get('wakeup_id') == data['test_first_cto_wakeup']
                      and run.get('agent_id') == route['cto']]
        if len(candidates) > 1:
            block('duplicate_test_first_cto_tasks')
            return
        if not candidates or candidates[0]['status'] in ('queued', 'dispatched', 'running'):
            if now - data['dispatched_at'] >= 1800:
                block('test_first_cto_progress_deadline')
            return
        recipient = candidates[0]
        if recipient['status'] != 'completed':
            block('test_first_cto_execution_' + recipient['status'])
            return
        try:
            decision = effects.decision(recipient)
        except (ValueError, TypeError, KeyError) as error:
            block('test_first_cto_invalid_decision:' + type(error).__name__)
            return
        data.update(cto_task=recipient['id'], decision=decision)
        try:import prospective_capacity
        except ImportError:from broker import prospective_capacity
        with broker.db() as con:
            capacity_experiment_qualified=prospective_capacity.qualified(con,issue,key,data)
        if (data.get('verified_tool_incident') and decision['action']=='request_correction'
                and data['verified_tool_incident'].get('cause_known') is not True
                and not capacity_experiment_qualified):
            block('test_first_unknown_argument_constraint_requires_diagnostic')
            return
        if decision['action'] != 'request_correction' or decision['optional_files']:
            block('test_first_cto_requires_replanning')
            return
        save('test_first_cto_correction', route['author'])
        return
    if prior['stage'] == 'test_first_cto_correction':
        if not effects.implementation_available(issue, route['author']):
            return
        marker = hashlib.sha256((issue + ':' + key + ':test-first-cto-correction').encode()).hexdigest()
        instruction = ('CONTROLLER CTO TESTS-ONLY CORRECTION: ' + data['decision']['reason']
                       + '. Resume the assigned workspace; edit only the declared new '
                         'test, preserve product code and all baseline tests. Run the '
                         'complete pinned suite. The controller must independently '
                         'capture Red before any implementation. This is one bounded '
                         'correction, not permission to change the contract. Follow the pinned '
                         'framework: for python3 -m unittest use unittest.TestCase and test_ '
                         'methods without pytest imports, fixtures, decorators or new dependencies. '
                         'Import/collection errors are not Red; do not install packages or change the runner.')
        wakeup = effects.ensure_wakeup(issue, route['author'], data['cto_task'], marker,
                                      instruction, allow_create=effects.remaining_calls() >= route['minimum_calls'])
        if wakeup is None:
            return
        data['test_first_correction_wakeup'] = wakeup['id']
        data['correction_dispatched_at'] = now
        save('test_first_cto_correction_wait', route['author'])
        return
    if prior['stage'] == 'test_first_cto_correction_wait' and now - data['correction_dispatched_at'] >= 1800:
        block('test_first_cto_correction_not_started')



def diagnostic_presentation(data):
    """Bounded index of durable evidence, never replace or validate a verdict."""
    diagnostic=data.get('diagnostic') or {}
    if not isinstance(diagnostic,dict):raise ValueError('structured pre-Red diagnostic required')
    result={'source_task':data.get('source_task'),'error':data.get('error'),
        'diagnostic':{k:diagnostic[k] for k in ('kind','category','task_id','issue_id','reason','tool','structure',
            'exit_code','command','manifest_sha256','test_sha256','output_sha256','tests_executed',
            'red_verified','delivery_approval') if k in diagnostic},
        'full_diagnostic_sha256':hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),
        'output_excerpt_omitted':len(str(diagnostic.get('output_excerpt') or ''))>512,
        'delivery_approval':False,'author_retry_authorized':False}
    excerpt=diagnostic.get('output_excerpt')
    if isinstance(excerpt,str) and len(excerpt)<=512:
        result['diagnostic']['output_excerpt']=excerpt
    if len(json.dumps(result,sort_keys=True))>2000:raise ValueError('pre-Red diagnostic index exceeds fixed bound')
    return result


def lost_lineage(current, history, runs, cto):
    """Restore only a recorded failed CTO pointer; never dispatch or approve."""
    if (current.get('phase')!='test_first' or current.get('error')!='test_author_execution_failed'
            or current.get('control_error')!='ValueError:handoff identity drift'
            or current.get('test_first_cto_wakeup') or current.get('lineage_repair')
            or not current.get('diagnostic')
            or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
        return None
    candidates=[d for d in history if d.get('phase')=='test_first'
        and d.get('error')=='test_first_cto_execution_failed' and d.get('test_first_cto_wakeup')
        and d.get('diagnostic')==current['diagnostic']]
    pointers={d['test_first_cto_wakeup'] for d in candidates}
    if len(pointers)!=1:return None
    pointer=next(iter(pointers))
    recipients=[r for r in runs if r.get('agent_id')==cto and r.get('wakeup_id')==pointer]
    if len(recipients)!=1 or recipients[0].get('status')!='failed':return None
    restored=dict(candidates[0])
    restored.pop('control_error',None);restored.pop('control_error_count',None)
    restored['lineage_repair']=dict(operation='restore_recorded_pre_red_cto_pointer_v1',
        previous_blocker=current,failed_cto_task=recipients[0]['id'],
        author_retry_authorized=False,delivery_approval=False)
    return restored


def reconcile(broker, route, runs, effects):
    """Return implementation-only runs once Red has been proven; else None."""
    issue = route['issue_id']
    authors = sorted((r for r in runs if r.get('agent_id') == route['author']),
                     key=lambda r: (r.get('created_at') or '', r['id']))
    with broker.db() as con:
        red_row = con.execute('SELECT task_id,receipt FROM test_first_red WHERE issue_id=?',
                              (issue,)).fetchone()
    if not red_row:
        if not authors:
            return None
        source = authors[-1]
        try:import template_author_executor
        except ImportError:from broker import template_author_executor
        template_author_executor.observe(broker,route,source)
        if source['status'] == 'failed' and hasattr(effects, 'capture_failed_test_checkpoint'):
            checkpoint = effects.capture_failed_test_checkpoint(issue, source['id'])
            if checkpoint and checkpoint.get('status') == 'red_captured':
                return None  # Next tick validates checkpoint provenance and independent review.
        with broker.db() as con:
            prior = handoffs.load(con, source['id'])
            if (prior and source.get('status')=='failed' and prior['issue_id']==issue
                    and json.loads(prior['data']).get('control_error')=='ValueError:handoff identity drift'):
                active=con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
                history=[json.loads(r[0]) for r in con.execute(
                    'SELECT data FROM delivery_handoff_events WHERE source_task=? AND stage=? ORDER BY id',
                    (source['id'],'test_first_blocked'))]
                restored=lost_lineage(json.loads(prior['data']),history,runs,route['cto']) if not active else None
                if restored:
                    handoffs.save(con,source['id'],issue,'test_first_blocked',route['cto'],restored,time.time())
                    return None
            surgical_execution=bool(source.get('wakeup_id') and any(
                json.loads(row[0]).get('surgical_wakeup')==source['wakeup_id'] for row in
                con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',(issue,))))
            if prior and prior['stage']=='diagnose_cto':
                preserved=json.loads(prior['data'])
                if (preserved.get('phase')=='test_first'
                        and preserved.get('control_error')=='ValueError:handoff instruction too large'
                        and not preserved.get('test_first_cto_wakeup')):
                    presentation=diagnostic_presentation(preserved)
                    preserved.setdefault('diagnostic_presentation_recovery',dict(
                        operation='bounded_pre_red_diagnostic_presentation_v1',
                        prior_control_error=preserved['control_error'],source_task=source['id'],
                        diagnostic_sha256=presentation['full_diagnostic_sha256'],
                        approval=False,author_restarted=False))
                    handoffs.save(con,source['id'],issue,'technical_decision_required',
                        route['cto'],preserved,time.time())
                    prior=handoffs.load(con,source['id'])
        try:import fenced_patch_diagnosis
        except ImportError:from broker import fenced_patch_diagnosis
        if fenced_patch_diagnosis.enrich(broker,route,runs,source,prior,effects):
            return None
        try:import cto_prompt_bound_recovery
        except ImportError:from broker import cto_prompt_bound_recovery
        if cto_prompt_bound_recovery.recover(broker,route,runs,source,prior,effects):
            return None
        failed_authors = [run for run in authors if run['status'] == 'failed']
        completed_authors = [run for run in authors if run['status'] == 'completed']
        if prior and prior['stage'] in ('test_first_cto_diagnosis', 'test_first_cto_correction',
                                       'test_first_selected_read_recovery_pending','test_first_selected_read_recovery_wait',
                                       'test_first_surgical_recovery_pending','test_first_surgical_recovery_wait',
                                       'test_first_cto_correction_wait', 'test_first_blocked','calibration_rework','calibration_failure_plan',
                                       'test_first_bootstrap_recovery_pending','test_first_bootstrap_recovery_wait',
                                       'test_first_artifact_recovery_pending','test_first_artifact_recovery_wait',
                                       'test_first_provider_recovery_pending','test_first_provider_recovery_wait',
                                       'test_first_transport_recovery_pending','test_first_transport_recovery_wait',
                                       'test_first_integration_recovery_pending','test_first_integration_recovery_wait'):
            technical_recovery(broker, route, runs, source, prior, effects)
            return None
        if (source['status'] == 'completed' and prior
                and prior['stage'] in ('technical_decision_required',
                                       'retry_test_path_intent',
                                       'retry_test_path_budget_paused',
                                       'awaiting_test_path_correction')
                and json.loads(prior['data']).get('error') ==
                ('ValueError:test-first test path mismatch'
                 if prior['stage'] == 'technical_decision_required'
                 else 'test_first_path_mismatch')
                and len(completed_authors) == 1):
            expected = route['test_first_files']
            if (not isinstance(expected, list) or len(expected) != 1
                    or not isinstance(expected[0], str)):
                raise ValueError('test-first exact path unavailable for correction')
            marker = hashlib.sha256((issue + ':' + source['id'] +
                                     ':correct-test-path').encode()).hexdigest()
            instruction = (
                'CONTROLLER TEST-FIRST PATH CORRECTION. The prior tests-only '
                'snapshot was rejected. The single declared new test path is '
                + expected[0] + ' relative to /workspace. Inspect the existing '
                'workspace; put the regression test at exactly that path and '
                'remove any accidental undeclared test file. Do not edit '
                'product code or pre-existing tests. Run the complete pinned '
                'suite and report the genuine Red. This is one bounded '
                'correction, not permission to revise the contract.')
            data = {'source_task': source['id'], 'phase': 'test_first',
                    'error': 'test_first_path_mismatch', 'retry_limit': 1,
                    'expected_test_file': expected[0],
                    'dispatch_marker': marker}
            if prior['stage'] == 'technical_decision_required':
                with broker.db() as con:
                    handoffs.save(con, source['id'], issue,
                                  'retry_test_path_intent', route['author'],
                                  data, time.time())
            wakeup = effects.ensure_wakeup(
                issue, route['author'], source['id'], marker, instruction,
                allow_create=effects.remaining_calls() >= route['minimum_calls'])
            if wakeup is None:
                with broker.db() as con:
                    handoffs.save(con, source['id'], issue,
                                  'retry_test_path_budget_paused', 'budget',
                                  data, time.time())
                return None
            data['wakeup_id'] = wakeup['id']
            with broker.db() as con:
                if prior['stage'] != 'awaiting_test_path_correction':
                    handoffs.save(con, source['id'], issue,
                                  'awaiting_test_path_correction', route['author'],
                                  data, time.time())
            return None
        if (source['status'] == 'failed'
                and not surgical_execution
                and source.get('failure_reason') == 'idle_watchdog'
                and len(failed_authors) == 1):
            if not effects.implementation_available(issue, route['author']):
                with broker.db() as con:
                    handoffs.save(con, source['id'], issue, 'awaiting_test_author_release',
                                  'controller', {'source_task': source['id'], 'phase': 'test_first',
                                                 'error': 'idle_watchdog'}, time.time())
                return None
            marker = hashlib.sha256((issue + ':' + source['id'] +
                                     ':retry-tests-only').encode()).hexdigest()
            instruction = (
                'CONTROLLER TEST-FIRST RETRY after idle_watchdog. Resume the '
                'same assigned /workspace. This is still PHASE 1 TESTS ONLY: '
                'create or finish the new regression test, do not edit product '
                'code, and run the complete pinned suite to observe Red. '
                'Preserve all pre-existing tests. Do not claim Red unless it '
                'actually ran. A second failure will not be retried automatically.')
            data = {'source_task': source['id'], 'phase': 'test_first',
                    'error': 'idle_watchdog', 'retry_limit': 1,
                    'dispatch_marker': marker}
            if prior and prior['stage'] not in (
                    'test_author_active', 'technical_decision_required',
                    'retry_test_author_intent',
                    'retry_test_author_budget_paused', 'awaiting_test_author_retry',
                    'awaiting_test_author_release'):
                raise ValueError('test-author retry source stage drift')
            if not prior or prior['stage'] in ('test_author_active',
                                               'technical_decision_required'):
                with broker.db() as con:
                    handoffs.save(con, source['id'], issue,
                                  'retry_test_author_intent', route['author'],
                                  data, time.time())
            wakeup = effects.ensure_wakeup(
                issue, route['author'], source['id'], marker, instruction,
                allow_create=effects.remaining_calls() >= route['minimum_calls'])
            if wakeup is None:
                with broker.db() as con:
                    handoffs.save(con, source['id'], issue,
                                  'retry_test_author_budget_paused', 'budget',
                                  data, time.time())
                return None
            data['wakeup_id'] = wakeup['id']
            with broker.db() as con:
                if not prior or prior['stage'] != 'awaiting_test_author_retry':
                    handoffs.save(con, source['id'], issue,
                                  'awaiting_test_author_retry', route['author'],
                                  data, time.time())
            return None
        if prior and prior['stage'] == 'technical_decision_required':
            technical_recovery(broker, route, runs, source, prior, effects)
            return None
        if source['status'] in ('queued', 'dispatched', 'running'):
            with broker.db() as con:
                if not handoffs.load(con, source['id']):
                    handoffs.save(con, source['id'], issue, 'test_author_active',
                                  route['author'], {'source_task': source['id'],
                                  'phase': 'test_first'}, time.time())
            return None
        if source['status'] != 'completed':
            error = 'test_author_execution_' + source['status']
        else:
            try:
                effects.capture_test_first_red({'task_id': source['id']})
                return None  # Next tick verifies durable Red before waking anyone.
            except Exception as failure:
                error = type(failure).__name__ + ':' + str(failure)[:200]
        with broker.db() as con:
            diagnostic = effects.test_first_failure(issue, source['id'])
            if (not diagnostic and source['status']=='failed'
                    and 'restricted broker stream failed: native_prompt_bounds' in (source.get('error') or '')):
                diagnostic={'kind':'native_pre_model_failure','category':'native_prompt_bounds',
                    'task_id':source['id'],'issue_id':issue,'tests_executed':False,
                    'red_verified':False,'delivery_approval':False,
                    'next_action':'Inspect native brief/handoff bounds; do not prescribe test repairs without executed tests'}
            handoffs.save(con, source['id'], issue, 'technical_decision_required',
                          route['cto'], {'source_task': source['id'], 'phase': 'test_first',
                          'error': error, 'diagnostic': diagnostic,
                          'required_action': 'repair_tests_only_or_red'}, time.time())
        return None
    test_task, red = red_row['task_id'], json.loads(red_row['receipt'])
    source = next((r for r in authors if r['id'] == test_task), None)
    checkpoint_source = False
    if source and source['status'] == 'failed':
        try:
            import failed_test_checkpoint
        except ImportError:
            from broker import failed_test_checkpoint
        with broker.db() as con:
            checkpoint_source = failed_test_checkpoint.qualified(con, issue, test_task, red)
    if not source or (source['status'] != 'completed' and not checkpoint_source) or red['task_id'] != test_task:
        raise ValueError('test-first Red source identity drift')
    try:
        import test_revision_review
    except ImportError:
        from broker import test_revision_review
    if not test_revision_review.reconcile(broker, route, runs, effects, red):
        return None
    try:
        import remediation_test_review
    except ImportError:
        from broker import remediation_test_review
    if remediation_test_review.record_gate(broker, route, red, effects):
        return None  # R1 never creates an implement-after-red wakeup on this card.
    marker = hashlib.sha256((issue + ':' + test_task + ':implement-after-red').encode()).hexdigest()
    instruction = ('CONTROLLER RED VERIFIED: ' + red['red']['manifest_sha256'] + '. '
                   'Now implement product code in the same /workspace. The tests-only '
                   'snapshot is frozen. Do not edit existing or new tests, do not replay '
                   'Red, and do not copy implementation from a prior attempt. The '
                   'controller will run Green and compare test hashes before review.')
    wakeup = effects.ensure_wakeup(issue, route['author'], test_task, marker, instruction,
                                   allow_create=effects.remaining_calls() >= route['minimum_calls'])
    if wakeup is None:
        with broker.db() as con:
            prior = handoffs.load(con, test_task)
            if not prior or prior['stage'] != 'budget_paused':
                handoffs.save(con, test_task, issue, 'budget_paused', 'budget',
                              {'source_task': test_task, 'phase': 'test_first',
                               'resume_stage': 'implement_after_red'}, time.time())
        return None
    implementations = [r for r in authors if r['id'] != test_task
                       and r.get('wakeup_id') == wakeup['id']]
    if len(implementations) > 1:
        raise ValueError('duplicate test-first implementation tasks')
    if not implementations:
        with broker.db() as con:
            prior = handoffs.load(con, test_task)
            if not prior or prior['stage'] != 'awaiting_implementation':
                handoffs.save(con, test_task, issue, 'awaiting_implementation',
                              route['author'], {'source_task': test_task,
                              'phase': 'test_first', 'wakeup_id': wakeup['id']}, time.time())
        return None
    first = implementations[0]
    return [r for r in runs if r.get('agent_id') != route['author']
            or (r['id'] != test_task and (r.get('created_at') or '', r['id']) >=
                (first.get('created_at') or '', first['id']))]
