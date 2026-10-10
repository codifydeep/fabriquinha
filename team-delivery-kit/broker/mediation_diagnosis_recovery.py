"""Once-only changed mediation transport, never a reset of prior recoveries."""
import copy
import json
try:from provider_diagnosis_recovery import digest
except ImportError:from broker.provider_diagnosis_recovery import digest

PROXY='sha256:7b21bc9b5df472dfdf08f025153b28045b1ccf02e39dd4fdf27b3939c372d193'


def prepare(state,red,route,config,task,reads,qualification,failure_receipt):
    diagnosis=state.get('rejection_diagnosis',{})
    old=diagnosis.get('provider_mediation_recovery')
    if old:
        if old['failed_task']!=task['id'] or old['qualification']!=qualification:
            raise ValueError('mediation transport recovery already consumed')
        return state
    paths=['/evidence/'+tree+'/'+path for tree in
        (('candidate',) if config.get('initial_review') else ('candidate','previous'))
        for path in route['test_first_files']]
    failure=diagnosis.get('failure',{})
    if (state.get('status')!='blocked' or state.get('evidence_policy')!=1
            or state.get('terminal_contract')!='typed-review-v1' or not state.get('review_task')
            or state.get('decision',{}).get('action')!='reject_test_revision'
            or diagnosis.get('status')!='blocked'
            or diagnosis.get('mediation_contract')!='immutable-review-reconsideration-v1'
            or diagnosis.get('target')!=route['cto']
            or failure.get('operation')!='task_completion' or failure.get('task_id')!=task.get('id')
            or task.get('status')!='failed' or task.get('failure_reason')!='agent_error.provider_server_error'
            or task.get('agent_id')!=route['cto'] or task.get('issue_id')!=route['issue_id']
            or task.get('wakeup_id')!=diagnosis.get('wakeup_id')
            or len({route['author'],config['reviewer'],route['cto']})!=3
            or state.get('source_task')!=red['task_id'] or state.get('candidate_volume')!=red['volume']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or qualification.get('operation')!='provider_mediation_transport_qualification_v1'
            or qualification.get('proxy_image')!=PROXY
            or qualification.get('model')!='anthropic/claude-haiku-5.5'
            or qualification.get('actual_artifact_read') is not False
            or qualification.get('worker_tool_executed') is not False or qualification.get('delivery_approval') is not False
            or failure_receipt.get('version')!='acp-failure-receipt-v1'
            or failure_receipt.get('method')!='session/prompt' or failure_receipt.get('approval') is not False
            or not paths or any(type(reads.get(p,{}).get('lines')) is not int
                or reads[p]['lines']<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('exact failed mediation, frozen reads and qualified changed transport required')
    result=copy.deepcopy(state)
    updated=dict(status='dispatch_intent',target=route['cto'],provider_mediation_recovery=dict(
        operation='fresh_readonly_mediation_transport_v1',failed_task=task['id'],qualification=qualification,
        prior_diagnosis=copy.deepcopy(diagnosis),failure_receipt=failure_receipt,
        read_receipt_sha256=digest(reads),manifest_sha256=state['manifest_sha256'],attempt_limit=1,
        historical_http_cause_proven=False,author_restarted=False,delivery_approval=False))
    for key in ('schema_recovery','typed_transport_recovery'):
        if key in diagnosis:updated[key]=copy.deepcopy(diagnosis[key])
    result['rejection_diagnosis']=updated
    return result


def resume(b,issue,failed_task,qualification_execution,operation):
    try:import controller_maintenance as maintenance,native,handoff_runtime,test_revision_review,provider_diagnosis_recovery
    except ImportError:from broker import controller_maintenance as maintenance,native,handoff_runtime,test_revision_review,provider_diagnosis_recovery
    with b.LOCK:
        with b.db() as c:
            barrier=maintenance.current(c)
            if not barrier or barrier['stage']!='sealed' or barrier['operation_id']!=operation:
                raise ValueError('exact sealed maintenance required')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                raise ValueError('idle leases required')
            config,state=map(json.loads,c.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone())
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            red=json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
            qualification=json.loads(c.execute('SELECT proof FROM provider_mediation_qualifications WHERE execution_id=?',(qualification_execution,)).fetchone()[0])
            bindings=c.execute('SELECT n.request_id,n.scope,l.status FROM native_bindings n JOIN leases l USING(request_id) '
                'WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',(failed_task,route['cto'],issue)).fetchall()
            if (not route.get('enabled') or len(bindings)!=1 or bindings[0]['status']!='closed'
                    or bindings[0]['scope'].split(':')[-2:]!=['planning',failed_task]):
                raise ValueError('enabled route and closed exact CTO binding required')
            failure=json.loads(c.execute('SELECT receipt FROM acp_failure_receipts WHERE request_id=? AND method=?',
                (bindings[0]['request_id'],'session/prompt')).fetchone()[0])
        if maintenance.native_active(b):raise ValueError('native idle required')
        if provider_diagnosis_recovery.proxy_info(b)['Image']!=qualification['proxy_image']:
            raise ValueError('installed qualified proxy required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if settings['agents'].get(route['cto'])!='planning':raise ValueError('CTO planning mode required')
        task=native.task_record(settings,failed_task,route['cto'])
        reviewer=native.task_record(settings,state['review_task'],config['reviewer'])
        if (reviewer.get('status')!='completed' or reviewer.get('issue_id')!=issue
                or reviewer.get('wakeup_id')!=state.get('wakeup_id')
                or fx.decision(reviewer)!=state['decision'] or fx.remaining_calls()<route['minimum_calls']):
            raise ValueError('original independent review and reserve required')
        test_revision_review.validate_evidence(b,route,state,state['decision'])
        updated=prepare(state,red,route,config,task,fx.read_evidence(task),qualification,failure)
        with b.db() as c:
            if json.loads(c.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])!=state:
                raise ValueError('mediation changed before recovery')
        test_revision_review._save_rejection(b,route,updated)
    return dict(status='dispatch_intent',attempt_limit=1,author_restarted=False,delivery_approval=False)
