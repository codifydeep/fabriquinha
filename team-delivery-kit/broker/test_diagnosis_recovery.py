"""Operator-admitted, once-only fresh CTO diagnosis after a typed rejection.

Never recover an invalid verdict or infer a missing legacy constraint. Normal
immutable review reconciliation validates the NEW decision and observed reads.
No worker endpoint exposes this admission operation.
"""
import hashlib
import json
import re

JSON_FEEDBACK_PROXY='sha256:7b21bc9b5df472dfdf08f025153b28045b1ccf02e39dd4fdf27b3939c372d193'


class AutomaticEffects:
    """Controller-owned observations only; no worker admission endpoint."""
    def __init__(self,b):self.b=b
    def idle(self):
        try:import controller_maintenance as maintenance
        except ImportError:from broker import controller_maintenance as maintenance
        with self.b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return False
            barrier=maintenance.current(con)
            if barrier and barrier['stage']!='released':return False
        return not maintenance.native_active(self.b)
    def candidate(self,issue):
        try:import native,handoff_runtime,test_revision_review,execution_diagnosis_recovery
        except ImportError:from broker import native,handoff_runtime,test_revision_review,execution_diagnosis_recovery
        with self.b.db() as con:
            row=con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
            if not row:return None
            config,state=map(json.loads,row)
            diagnosis=state.get('rejection_diagnosis',{})
            if diagnosis.get('schema_recovery'):return (state,)
            failure=diagnosis.get('failure',{})
            if (diagnosis.get('status')!='blocked' or failure.get('operation')!='task_completion'
                    or failure.get('detail')!='CTO diagnosis did not complete'):return None
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            bindings=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) '
                'WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (failure['task_id'],route['cto'],issue)).fetchall()
            if len(bindings)!=1 or bindings[0]['status']!='closed':return None
            execution=bindings[0]['request_id']
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        settings=json.loads((self.b.STATE/'native.json').read_text())
        task=native.task_record(settings,failure['task_id'],route['cto'])
        reviewer=native.task_record(settings,state['review_task'],config['reviewer'])
        if (task.get('failure_reason')!='agent_error.provider_server_error'
                or reviewer.get('status')!='completed' or reviewer.get('issue_id')!=issue):return None
        fx=handoff_runtime.Effects(self.b,settings)
        if fx.remaining_calls()<route['minimum_calls']:return None
        if fx.decision(reviewer)!=state.get('decision'):raise ValueError('original review decision drift')
        test_revision_review.validate_evidence(self.b,route,state,state['decision'])
        receipt=execution_diagnosis_recovery.format_rejection(self.b,execution,expected_image=JSON_FEEDBACK_PROXY)
        if receipt.get('category')!='typed_arguments_invalid':return None
        return state,red,task,route,config,fx.read_evidence(task),receipt,execution
    def persist(self,issue,previous,updated):
        try:import test_revision_review
        except ImportError:from broker import test_revision_review
        with self.b.LOCK:
            if not self.idle():raise TimeoutError('diagnosis capacity changed; retain prior failure')
            with self.b.db() as con:
                current=json.loads(con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
                if current!=previous:raise ValueError('diagnosis changed before automatic admission')
                route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            test_revision_review._save_rejection(self.b,route,updated)


def automatic(b,issue,effects=None):
    """One changed format policy; never accept the failed submission or retry author."""
    fx=effects or AutomaticEffects(b)
    if not fx.idle():return dict(stage='awaiting_capacity',delivery_approval=False)
    args=fx.candidate(issue)
    if args is None:return dict(stage='not_applicable',delivery_approval=False)
    if args[0].get('rejection_diagnosis',{}).get('schema_recovery'):
        return dict(stage='recovery_consumed',delivery_approval=False)
    updated=prepare(*args)
    fx.persist(issue,args[0],updated)
    return dict(stage='fresh_diagnosis_admitted',attempt_limit=1,delivery_approval=False)


def prepare(state,red,task,route,config,reads,receipt,execution):
    diagnosis=state.get('rejection_diagnosis',{})
    prior=diagnosis.get('schema_recovery')
    if prior:
        if (prior['failed_task']!=task['id'] or prior['execution_id']!=execution
                or prior['rejection_receipt']!=receipt):
            raise ValueError('diagnosis recovery identity drift')
        return state
    failure=diagnosis.get('failure',{});shape=receipt.get('response_shape',{})
    malformed=(receipt.get('category')=='typed_arguments_invalid'
        and shape.get('arguments_json_valid') is False
        and shape.get('arguments_schema_valid') is None
        and shape.get('arguments_rejection') not in ('argument_type','argument_size'))
    schema_rejected=(receipt.get('category') in {'typed_schema_violation','typed_schema_type',
        'typed_schema_required','typed_schema_additionalProperties','typed_schema_enum',
        'typed_schema_minLength','typed_schema_maxLength','typed_schema_maxItems'}
        and shape.get('arguments_json_valid') is True and shape.get('arguments_schema_valid') is False)
    paths=['/evidence/'+tree+'/'+name for tree in
        (('candidate',) if config.get('initial_review') else ('candidate','previous'))
        for name in route['test_first_files']]
    if (state.get('status')!='blocked' or state.get('evidence_policy')!=1
            or state.get('terminal_contract')!='typed-review-v1'
            or not state.get('review_task') or diagnosis.get('status')!='blocked'
            or diagnosis.get('target')!=route['cto']
            or failure.get('task_id')!=task['id'] or failure.get('operation')!='task_completion'
            or failure.get('detail')!='CTO diagnosis did not complete'
            or task.get('status')!='failed' or task.get('agent_id')!=route['cto']
            or task.get('issue_id')!=route['issue_id'] or task.get('wakeup_id')!=diagnosis.get('wakeup_id')
            or route['cto'] in (route['author'],config['reviewer'])
            or state.get('source_task')!=red['task_id']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or not execution or receipt.get('operation')!='rejected_typed_decision_adapter_v1'
            or not (malformed or schema_rejected)
            or not re.fullmatch(r'[a-f0-9]{64}',receipt.get('upstream_sha256',''))
            or receipt.get('worker_tool_executed') is not False or receipt.get('delivery_approval') is not False
            or any(shape.get(k) is not v for k,v in {'parsed':True,'terminal':True,
                'legacy_function_call':False,'expected_tool':True}.items())
            or shape.get('submissions')!=1 or shape.get('content_shape')!='empty'
            or not paths or any(type(reads.get(p,{}).get('lines')) is not int
                or reads[p]['lines']<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('exact closed typed rejection and complete frozen reads required')
    result=json.loads(json.dumps(state))
    result['rejection_diagnosis']=dict(status='dispatch_intent',target=route['cto'],
        schema_recovery=dict(operation='fresh_readonly_cto_schema_diagnosis_v1',
            failed_task=task['id'],execution_id=execution,manifest_sha256=state['manifest_sha256'],
            rejection_receipt=receipt,prior_diagnosis=diagnosis,attempt_limit=1,
            read_receipt_sha256=hashlib.sha256(json.dumps(reads,sort_keys=True).encode()).hexdigest(),
            author_restarted=False,delivery_approval=False))
    return result


def resume(b,payload):
    """Called only by the operator CLI, under an existing sealed barrier."""
    try:import native,handoff_runtime,controller_maintenance
    except ImportError:from broker import native,handoff_runtime,controller_maintenance
    if set(payload)!={'issue_id','failed_task','execution_id','receipt','proxy_image','operation_id'}:
        raise ValueError('exact diagnosis admission payload required')
    with b.LOCK,b.db() as con:
        maintenance=controller_maintenance.current(con)
        if not maintenance or maintenance['stage']!='sealed' or maintenance['operation_id']!=payload['operation_id']:
            raise ValueError('sealed exact maintenance required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy['Image']!=payload['proxy_image']
                or proxy['Config']['Labels'].get('com.docker.compose.project')!=b.PREFIX
                or proxy['Config']['Labels'].get('com.docker.compose.service')!='model-proxy'):
            raise ValueError('installed owned proxy identity required')
        binding=con.execute('SELECT task_id,agent_id,issue_id FROM native_bindings WHERE request_id=?',
            (payload['execution_id'],)).fetchone()
        config,state=map(json.loads,con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
            (payload['issue_id'],)).fetchone())
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
            (payload['issue_id'],)).fetchone()[0])
        if not binding or tuple(binding)!=(payload['failed_task'],route['cto'],payload['issue_id']):
            raise ValueError('native rejection binding drift')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,payload['failed_task'],route['cto'])
        reviewer=native.task_record(settings,state['review_task'],config['reviewer'])
        if reviewer.get('status')!='completed' or reviewer.get('issue_id')!=route['issue_id']:
            raise ValueError('closed independent original review required')
        if controller_maintenance.native_active(b):raise ValueError('native idle required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('lease idle required')
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
            (payload['issue_id'],)).fetchone()[0])
        fx=handoff_runtime.Effects(b,settings)
        if fx.remaining_calls()<route['minimum_calls']:raise ValueError('diagnosis reserve required')
        updated=prepare(state,red,task,route,config,fx.read_evidence(task),payload['receipt'],payload['execution_id'])
    # Persist the trial AND its handoff atomically. Updating only the trial
    # leaves the sequence supervisor reading the old terminal blocked handoff.
    try:import test_revision_review
    except ImportError:from broker import test_revision_review
    with b.LOCK:
        test_revision_review._save_rejection(b,route,updated)
    return dict(status=updated['rejection_diagnosis']['status'],attempt_limit=1,
        source_author_restarted=False,delivery_approval=False)
