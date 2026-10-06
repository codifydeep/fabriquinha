"""Operator-qualified single surgical recovery, scoped to its exact wakeup."""
import hashlib
import json
import time
import uuid
try:
    import handoffs,native,handoff_runtime,artifact_transport_recovery
except ImportError:
    from broker import handoffs,native,handoff_runtime,artifact_transport_recovery


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS surgical_test_recoveries(issue_id TEXT PRIMARY KEY,config TEXT)')


def arm(b,payload):
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','failure'}:
        raise ValueError('exact surgical recovery required')
    for key in ('issue_id','source_task'):
        if str(uuid.UUID(payload[key]))!=payload[key]:raise ValueError('invalid surgical identity')
    failure=payload['failure']
    if (set(failure)!={'origin','category','status','execution_id','call_number'}
            or failure['origin']!='operator_verified_historical_proxy_metadata'
            or failure['category']!='artifact_test_methods_missing' or failure['status']!=502
            or type(failure['call_number']) is not int or failure['call_number']<1):
        raise ValueError('measured pre-tool artifact rejection required')
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            old=con.execute('SELECT config FROM surgical_test_recoveries WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            if old:
                config=json.loads(old[0])
                if config['request']!=payload:raise ValueError('surgical recovery identity drift')
                return config
            row=handoffs.load(con,payload['source_task']);data=json.loads(row['data']) if row else {}
            route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            route=json.loads(route_row[0]) if route_row else {}
            if (not row or row['issue_id']!=payload['issue_id'] or row['stage']!='test_first_blocked'
                    or data.get('error')!='test_first_correction_failed_after_cto_diagnosis'
                    or not route.get('enabled') or not route.get('test_first')):
                raise ValueError('blocked tests-only correction required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():raise ValueError('Red exists')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():raise ValueError('idle workers required')
            binding=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(payload['source_task'],)).fetchone()
            if not binding or binding[0]!=failure['execution_id']:raise ValueError('artifact rejection execution drift')
            history=[json.loads(r[0]) for r in con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',(payload['issue_id'],))]
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id']);authors=[r for r in runs if r.get('agent_id')==route['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source.get('id')
                or source.get('status')!='completed' or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest idle completed author required')
        sponsors=[h for h in history if h.get('framework_replan') and h.get('test_first_correction_wakeup')==source.get('wakeup_id')]
        if len(sponsors)!=1:raise ValueError('exact framework CTO sponsorship required')
        sponsor=sponsors[0];cto=next((r for r in runs if r['id']==sponsor.get('cto_task')), {})
        decision=handoff_runtime.Effects(b,settings).decision(cto)
        if (cto.get('status')!='completed' or cto.get('agent_id')!=route['cto'] or decision!=sponsor.get('decision')
                or decision.get('action')!='request_correction' or decision.get('optional_files')!=[]):
            raise ValueError('independent completed CTO decision required')
        diagnostic=json.loads((b.STATE/'test-first-incidents'/(source['id']+'.json')).read_text())
        if (diagnostic!=data.get('diagnostic') or diagnostic.get('kind')!='rejected_red'
                or diagnostic.get('command',[])[1:3]!=['-m','unittest']
                or set(diagnostic.get('test_sha256',{}))!=set(route['test_first_files'])
                or len(route['test_first_files'])!=1):raise ValueError('preserved exact rejected test required')
        proof=artifact_transport_recovery.verify_preserved_failure(b,source['id'],{'files':diagnostic['test_sha256']},failed=False)
        if (proof.get('verified') is not True or proof.get('baseline_unchanged') is not True
                or proof.get('task_id')!=source['id']):raise ValueError('verified preserved surgical source required')
        name=route['test_first_files'][0];digest=diagnostic['test_sha256'][name]
        config=dict(request=payload,source_task=source['id'],author=route['author'],cto=route['cto'],
            path='/workspace/'+name,expected_sha256=digest,proof=proof,cto_task=cto['id'],
            diagnostic_sha256=hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest(),delivery_approval=False)
        data.update(surgical_recovery=config)
        with b.db() as con:
            con.execute('INSERT INTO surgical_test_recoveries VALUES(?,?)',(payload['issue_id'],json.dumps(config,sort_keys=True)))
            handoffs.save(con,source['id'],payload['issue_id'],'test_first_surgical_recovery_pending',route['author'],data,time.time())
        return config


def for_task(b,issue,task):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT config FROM surgical_test_recoveries WHERE issue_id=?',(issue,)).fetchone()
        if not row or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone():return None
        config=json.loads(row[0]);handoff=handoffs.load(con,config['source_task'])
    if task.get('agent_id')!=config['author'] or task.get('id')==config['source_task']:return None
    if not handoff:raise ValueError('surgical source handoff missing')
    # A historical registration is not a permanent issue-wide tool policy.
    # Once its dispatch stage is consumed/replaced, give no surgical capability
    # and let later executions use their independently fenced ordinary tools.
    if handoff['stage']!='test_first_surgical_recovery_wait':return None
    data=json.loads(handoff['data'])
    if task.get('wakeup_id')!=data.get('surgical_wakeup'):
        raise ValueError('unbound surgical author execution')
    keys=('path','expected_sha256','protocol') if config.get('protocol')=='typed_v2' else ('path','expected_sha256')
    return {k:config[k] for k in keys}


def arm_typed(b,payload):
    """One changed-contract recovery; retain the consumed V1 grant and failure."""
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','qualification'}:
        raise ValueError('exact typed recovery required')
    for key in ('issue_id','source_task'):
        if str(uuid.UUID(payload[key]))!=payload[key]:raise ValueError('invalid typed identity')
    proof=payload['qualification']
    if (not isinstance(proof,dict) or proof.get('schema')!='surgical-typed-registry-probe-v2'
            or proof.get('status')!='passed' or proof.get('delivery_approval') is not False
            or proof.get('network')!='none' or proof.get('credentials_absent') is not True
            or proof.get('actual_registry') is not True or proof.get('fixture_removed') is not True
            or proof.get('actual_default_selection') is not True
            or proof.get('actual_acp_selection') is not True or proof.get('full_proxy_request_validation') is not True
            or proof.get('preserved_bodies') is not True or proof.get('stale_edit_denied') is not True
            or proof.get('legacy_write_denied') is not True or proof.get('readless_edit_denied') is not True
            or proof.get('response_gate_qualified') is not True
            or proof.get('worker_image')!=b.IMAGE):raise ValueError('qualified actual typed registry required')
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            oldrow=con.execute('SELECT config FROM surgical_test_recoveries WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            if not oldrow:raise ValueError('prior surgical grant required')
            old=json.loads(oldrow[0])
            if old.get('typed_request'):
                if old['typed_request']!=payload:raise ValueError('typed recovery already consumed')
                return old
            row=handoffs.load(con,payload['source_task']);data=json.loads(row['data']) if row else {}
            failure=data.get('transport_failure_receipt',{})
            binding=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(payload['source_task'],)).fetchone()
            if (not row or row['issue_id']!=payload['issue_id'] or row['stage']!='test_first_blocked'
                    or data.get('error')!='test_first_correction_failed_after_cto_diagnosis'
                    or failure.get('kind')!='surgical_pre_tool_rejection_v1'
                    or failure.get('category')!='invalid_surgical_response' or failure.get('status')!=502
                    or failure.get('write_tool_calls')!=0 or failure.get('task_id')!=payload['source_task']
                    or not binding or failure.get('execution_id')!=binding[0]):
                raise ValueError('exact consumed surgical pre-tool rejection required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():raise ValueError('Red exists')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():raise ValueError('idle workers required')
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
            if not route.get('enabled') or not route.get('test_first') or route['author']!=old['author'] or route['cto']!=old['cto']:
                raise ValueError('surgical route drift')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy.get('Image')!=proof.get('proxy_image') or not proxy.get('State',{}).get('Running')
                or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('qualified installed proxy required')
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==old['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source.get('id')
                or source.get('status')!='failed' or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest idle failed surgical author required')
        prior=old.copy()
        with b.db() as con:grant=handoffs.load(con,old['source_task'])
        if not grant or source.get('wakeup_id')!=json.loads(grant['data']).get('surgical_wakeup'):
            raise ValueError('failed task not bound to consumed surgical grant')
        artifact=artifact_transport_recovery.verify_preserved_failure(b,source['id'],
            {'files':{old['path'].removeprefix('/workspace/'):old['expected_sha256']}},failed=True)
        if not artifact.get('verified') or not artifact.get('baseline_unchanged'):raise ValueError('preserved failure verification required')
        config={**old,'source_task':source['id'],'protocol':'typed_v2','typed_request':payload,
            'previous_grant':prior,'typed_source_proof':artifact,'delivery_approval':False}
        data['surgical_recovery']=config
        with b.db() as con:
            con.execute('UPDATE surgical_test_recoveries SET config=? WHERE issue_id=?',
                (json.dumps(config,sort_keys=True),payload['issue_id']))
            handoffs.save(con,source['id'],payload['issue_id'],'test_first_surgical_recovery_pending',old['author'],data,time.time())
        return config


def worker_config(b,request_id,issue):
    with b.db() as con:
        initialize(con)
        if not con.execute('SELECT 1 FROM surgical_test_recoveries WHERE issue_id=?',(issue,)).fetchone():return None
        binding=con.execute('SELECT task_id,agent_id FROM native_bindings WHERE request_id=?',(request_id,)).fetchone()
    if not binding:raise ValueError('surgical task binding missing')
    settings=json.loads((b.STATE/'native.json').read_text())
    return for_task(b,issue,native.task_record(settings,binding['task_id'],binding['agent_id']))


def arm_selection(b,payload):
    """One registration repair after a proven zero-call, zero-tool rejection."""
    return _arm_selection(b,payload,acp=False)


def arm_acp_selection(b,payload):
    """One exact-ACP repair, without resetting the consumed default repair."""
    return _arm_selection(b,payload,acp=True)


def arm_feedback(b,payload):
    """One qualified feedback repair; do not weaken rejection conditions."""
    return _arm_selection(b,payload,acp=True,feedback=True)


def _arm_selection(b,payload,*,acp,feedback=False):
    request_key='feedback_request' if feedback else 'acp_selection_request' if acp else 'selection_request'
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','qualification'}:
        raise ValueError('exact selection recovery required')
    for key in ('issue_id','source_task'):
        if str(uuid.UUID(payload[key]))!=payload[key]:raise ValueError('invalid selection identity')
    proof=payload['qualification']
    flags=('credentials_absent','actual_registry','actual_default_selection','actual_acp_selection','full_proxy_request_validation','fixture_removed',
        'preserved_bodies','stale_edit_denied','legacy_write_denied','readless_edit_denied','response_gate_qualified')
    if (not isinstance(proof,dict) or proof.get('schema')!='surgical-typed-registry-probe-v2'
            or proof.get('status')!='passed' or proof.get('delivery_approval') is not False
            or proof.get('network')!='none' or proof.get('worker_image')!=b.IMAGE
            or any(proof.get(key) is not True for key in flags)):
        raise ValueError('qualified complete tool selection required')
    if feedback and (proof.get('structured_feedback_visible') is not True or proof.get('invalid_candidate_preserved') is not True):
        raise ValueError('qualified actionable feedback qualification required')
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            oldrow=con.execute('SELECT config FROM surgical_test_recoveries WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            old=json.loads(oldrow[0]) if oldrow else {}
            if old.get(request_key):
                if old[request_key]!=payload:raise ValueError('selection recovery already consumed')
                return old
            row=handoffs.load(con,payload['source_task']);data=json.loads(row['data']) if row else {}
            failure=data.get('surgical_edit_rejections' if feedback else 'typed_acp_selection_failure' if acp else 'typed_selection_failure',{})
            binding=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(payload['source_task'],)).fetchone()
            identity_invalid=(not old.get('typed_request') or old.get('protocol')!='typed_v2'
                    or not row or row['issue_id']!=payload['issue_id'] or row['stage']!='test_first_blocked'
                    or data.get('error')!='test_first_correction_failed_after_cto_diagnosis'
                    or acp and not old.get('selection_request')
                    or failure.get('task_id')!=payload['source_task'] or failure.get('issue_id')!=payload['issue_id']
                    or not binding or failure.get('execution_id')!=binding[0])
            if feedback:
                if (identity_invalid or not old.get('acp_selection_request')
                        or failure.get('kind')!='rejected_surgical_edits_v2'
                        or failure.get('origin')!='operator_verified_native_results_and_offline_prepare_on_frozen_source'
                        or failure.get('tool_calls')!=2 or failure.get('rejected_tool_results')!=2
                        or failure.get('baseline_unchanged') is not True
                        or failure.get('test_sha256')!=old['expected_sha256']):
                    raise ValueError('exact rejected surgical edit source required')
            elif (identity_invalid or failure.get('kind')!=('typed_acp_selection_failure_v2' if acp else 'typed_tool_selection_failure_v2')
                    or failure.get('origin')!=('operator_verified_proxy_metadata_and_exact_acp_source' if acp
                        else 'operator_verified_proxy_metadata_and_offline_negative_control')
                    or failure.get('observed_proxy_category')!=('typed surgical tool missing from actual registry' if acp else 'invalid_request')
                    or failure.get('status')!=400
                    or failure.get('model_calls_consumed')!=0 or failure.get('tool_calls')!=0
                    or not acp and (failure.get('old_default_selection_has_tool') is not False
                        or failure.get('corrected_default_selection_has_tool') is not True)
                    or acp and failure.get('baseline_unchanged') is not True):
                raise ValueError('exact zero-call tool-selection failure required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():raise ValueError('Red exists')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():raise ValueError('idle workers required')
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
            if (not route.get('enabled') or not route.get('test_first') or route['author']!=old['author']
                    or route['cto']!=old['cto'] or route['author']==route['cto']):raise ValueError('selection route drift')
            grant=handoffs.load(con,old['source_task'])
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy.get('Image')!=proof.get('proxy_image') or not proxy.get('State',{}).get('Running')
                or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('qualified installed proxy required')
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==old['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source.get('id')
                or source.get('status')!='completed' or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest idle completed selection author required')
        if not grant or source.get('wakeup_id')!=json.loads(grant['data']).get('surgical_wakeup'):
            raise ValueError('selection task not bound to consumed grant')
        messages=native.task_messages(settings,source['id'])
        if feedback:
            uses=[m for m in messages if m.get('type')=='tool_use']
            edits=[m for m in uses if m.get('tool')=='surgical_test_edit']
            results=[m for m in messages if m.get('type')=='tool_result' and m.get('tool')=='surgical_test_edit']
            if (len(edits)!=2 or len(results)!=2 or any(m.get('tool') not in ('read_file','surgical_test_edit') for m in uses)
                    or any(not isinstance(m.get('input'),dict) or m['input'].get('path')!=old['path'] for m in edits)
                    or any('surgical_edit_rejected' not in str(m.get('output','')) or 'surgical_test_edit_v1' in str(m.get('output','')) for m in results)):
                raise ValueError('exact rejected surgical tool executions required')
            diagnostic=json.loads((b.STATE/('surgical-prepare-diagnosis-'+source['id']+'.json')).read_text())
            if (diagnostic.get('task_id')!=source['id'] or diagnostic.get('input_sha256')!=old['expected_sha256']
                    or diagnostic.get('baseline_unchanged') is not True
                    or diagnostic.get('categories')!=failure.get('categories')
                    or diagnostic.get('categories')!=['all tests must remain unittest discoverable','no preserved test methods']):
                raise ValueError('exact actionable diagnostic required')
        elif any(m.get('type') in ('tool_use','tool_result') for m in messages):
            raise ValueError('no tool execution required for selection recovery')
        artifact=artifact_transport_recovery.verify_preserved_failure(b,source['id'],
            {'files':{old['path'].removeprefix('/workspace/'):old['expected_sha256']}},failed=False)
        if not artifact.get('verified') or not artifact.get('baseline_unchanged'):raise ValueError('preserved selection source required')
        config={**old,'source_task':source['id'],request_key:payload,'previous_grant':old,
            'selection_source_proof':artifact,'selection_activity_sha256':hashlib.sha256(
                json.dumps(messages,sort_keys=True).encode()).hexdigest(),'delivery_approval':False}
        data['surgical_recovery']=config
        with b.db() as con:
            con.execute('UPDATE surgical_test_recoveries SET config=? WHERE issue_id=?',
                (json.dumps(config,sort_keys=True),payload['issue_id']))
            handoffs.save(con,source['id'],payload['issue_id'],'test_first_surgical_recovery_pending',old['author'],data,time.time())
        return config
