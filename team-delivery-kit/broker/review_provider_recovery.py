"""One evidence-bound review recovery after a qualified provider schema repair."""
import copy
import json


def prepare(state,red,task,reviewer,reads,qualification):
    old=state.get('provider_schema_recovery')
    if old:
        if old['failed_task']!=task['id'] or old['qualification']!=qualification:
            raise ValueError('provider schema recovery already consumed')
        return state
    paths={'/evidence/candidate/'+p for p in red['red']['test_sha256']}
    failure=state.get('review_failure') or {}
    if (state.get('status')!='blocked' or state.get('decision') or state.get('review_task')
            or state.get('terminal_contract')!='typed-review-v1'
            or failure.get('task_id')!=task.get('id')
            or failure.get('detail')!='independent test review did not complete'
            or task.get('status')!='failed' or task.get('failure_reason')!='agent_error.provider_server_error'
            or task.get('agent_id')!=reviewer or task.get('wakeup_id')!=state.get('wakeup_id')
            or state.get('source_task')!=red['task_id'] or state.get('candidate_volume')!=red['volume']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or not paths or any(reads.get(p,{}).get('lines',0)<=0
                or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)
            or qualification.get('operation')!='provider_review_transport_qualification_v1'
            or qualification.get('model')!='anthropic/claude-haiku-5.5'
            or qualification.get('delivery_approval') is not False
            or qualification.get('actual_artifact_read') is not False):
        raise ValueError('exact failed observed review and qualified schema repair required')
    result=copy.deepcopy(state)
    result['provider_schema_recovery']=dict(failed_task=task['id'],failed_wakeup=task['wakeup_id'],
        prior_failure=failure,qualification=qualification,manifest_sha256=state['manifest_sha256'],
        historical_http_cause_proven=False,attempt_limit=1,approval=False,author_restarted=False)
    result['status']='dispatch_intent'
    for key in ('wakeup_id','dispatched_at','marker','reason','review_failure','read_evidence'):
        result.pop(key,None)
    return result


def resume(b,payload):
    if not isinstance(payload,dict) or set(payload)!={'issue_id','failed_task','qualification_execution'}:
        raise ValueError('exact review recovery identifiers required')
    import native,handoff_runtime
    from provider_diagnosis_recovery import proxy_info
    with b.LOCK,b.db() as c:
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
            raise ValueError('idle recovery required')
        config,state=map(json.loads,c.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(payload['issue_id'],)).fetchone())
        if not config.get('initial_review'):raise ValueError('initial review recovery only')
        proof=json.loads(c.execute('SELECT proof FROM provider_review_qualifications WHERE execution_id=?',(payload['qualification_execution'],)).fetchone()[0])
        if proof['proxy_image']!=proxy_info(b)['Image']:raise ValueError('installed qualified proxy required')
        red=json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,payload['failed_task'],config['reviewer'])
        if task.get('issue_id')!=payload['issue_id']:raise ValueError('review issue drift')
        if any(t['status'] in ('queued','dispatched','running') for t in native.issue_task_runs(settings,payload['issue_id'])):
            raise ValueError('idle native review required')
        rows=c.execute('SELECT n.scope,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
            (task['id'],config['reviewer'],payload['issue_id'])).fetchall()
        if len(rows)!=1 or rows[0]['status']!='closed' or rows[0]['scope'].split(':')[-2:]!=['planning',task['id']]:
            raise ValueError('closed exact review lease required')
        reads=handoff_runtime.Effects(b,settings).read_evidence(task)
        updated=prepare(state,red,task,config['reviewer'],reads,proof)
        c.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',(json.dumps(updated,sort_keys=True),payload['issue_id']))
        return dict(status=updated['status'],failed_task=task['id'],delivery_approval=False,author_restarted=False)
