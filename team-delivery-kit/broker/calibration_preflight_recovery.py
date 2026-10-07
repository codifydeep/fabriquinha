"""Controller-only qualification of one corrected calibration schema preflight.

No worker endpoint. The operator supplies the sanitized proxy receipt, while
closed native identity, complete actual reads and current policy are checked
live. Only a fresh planner decision is queued, never a verdict replay or author.
"""
import hashlib,json,time


def check_policy(lane,config,state):
    from decision_schema import apply as schema
    from typed_decision_contract import apply as adapter,NAME
    note=lane.instruction(config,{**state,'stage':'cto_pending'})
    flags='\n'.join(line for line in note.splitlines() if line.startswith('DELIVERY_')
                    and not line.startswith('DELIVERY_REVIEW_READ_PATH:'))
    # Policy-only schema check. This is not source/read evidence; the live
    # read receipts are separately required before registration below.
    body=adapter(schema(dict(messages=[dict(role='user',content=flags)],tools=[])))
    properties=body['tools'][0]['function']['parameters']['properties']
    if (body['tool_choice']['function']['name']!=NAME
            or set(properties)!={'action','reason','optional_files'}
            or properties['optional_files'].get('maxItems')!=0
            or not set(properties['action']['enum'])<={'request_correction','request_test_revision','escalate_cto'}
            or 'DELIVERY_TYPED_TEST_DIAGNOSIS_V1' in note):
        raise ValueError('corrected nonapproving simple typed schema required')
    return hashlib.sha256(note.encode()).hexdigest()


def qualify(config,state,task,reads,rejection,execution_id):
    from proxy_request_rejections import record
    record(None,rejection)  # Validate exact sanitized shape without persisting it.
    expected=hashlib.sha256(b'observed non-approving test diagnosis contract required').hexdigest()
    note=task.get('handoff_note') or ''
    if (config.get('format_revision')!=1 or state.get('stage')!='blocked'
            or state.get('category')!='calibration_rework_rejected' or state.get('preflight_recovery')
            or state.get('author_wakeup') or state.get('peer_wakeup')
            or task.get('status')!='failed' or task.get('agent_id')!=config['cto']
            or task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state.get('cto_wakeup')
            or 'DELIVERY_TYPED_TEST_DIAGNOSIS_V1' not in note or 'DELIVERY_TYPED_DECISION_V1' not in note
            or 'CALIBRATION GATE REWORK' not in note
            or rejection['execution_id']!=execution_id or rejection['stage']!='contract'
            or rejection.get('origin')!={'module':'typed_decision_contract','line':378}
            or rejection['error_sha256']!=expected
            or any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
                   or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
        raise ValueError('exact failed fully inspected pre-upstream schema rejection required')


def register(b,issue,failed_task,rejection):
    try:import native,handoff_runtime,handoffs,calibration_rework as lane
    except ImportError:from broker import native,handoff_runtime,handoffs,calibration_rework as lane
    settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT source_task,config,state FROM calibration_reworks WHERE issue_id=?',(issue,)).fetchone()
            if not row:raise ValueError('existing calibration rework required')
            source,config,state=row[0],json.loads(row[1]),json.loads(row[2])
            prior=state.get('preflight_recovery')
            if prior:
                if prior['failed_task']!=failed_task or prior['rejection']!=rejection:raise ValueError('one immutable preflight recovery required')
                return prior
            bound=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) '
                'WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',(failed_task,issue,config['cto'])).fetchall()
            if (len(bound)!=1 or bound[0][1]!='closed' or con.execute(
                    "SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()):
                raise ValueError('one exact closed pre-Red planner and idle workers required')
            current=handoffs.load(con,source)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            if not route['enabled'] or route['contract_sha256']!=config['contract_sha256']:raise ValueError('enabled unchanged route required')
        task=native.task_record(settings,failed_task,config['cto']);reads=fx.read_evidence(task)
        qualify(config,state,task,reads,rejection,bound[0][0])
        if any(t['status'] in ('queued','dispatched','running') for t in native.issue_task_runs(settings,issue)):
            raise ValueError('no pending task during qualification')
        policy=check_policy(lane,config,state)
        receipt=dict(operation='calibration_schema_preflight_recovery_v1',failed_task=failed_task,
            rejection=rejection,previous_state=state,policy_sha256=policy,read_evidence=reads,
            decision_replayed=False,author_retry_authorized=False,delivery_approval=False,attempt_limit=1)
        new={**state,'stage':'cto_pending','preflight_recovery':receipt}
        for key in ('cto_wakeup','category','error_type','owner','intent_at','at'):new.pop(key,None)
        changed={**config,'format_revision':2}
        with b.db() as con:
            live=con.execute('SELECT config,state FROM calibration_reworks WHERE issue_id=?',(issue,)).fetchone()
            if (tuple(live)!=(row[1],row[2]) or handoffs.load(con,source)!=current or con.execute(
                    "SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('calibration source changed during qualification')
            con.execute('UPDATE calibration_reworks SET config=?,state=? WHERE issue_id=?',
                (json.dumps(changed,sort_keys=True),json.dumps(new,sort_keys=True),issue))
            data=json.loads(current['data']);data['calibration_rework']={'manifest_sha256':config['manifest_sha256'],'state':new}
            data['required_action']='CTO fresh decision under corrected schema; no author permission'
            handoffs.save(con,source,issue,'calibration_rework',config['cto'],data,time.time())
        return receipt
