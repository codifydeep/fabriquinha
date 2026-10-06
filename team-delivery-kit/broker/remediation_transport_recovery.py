"""Controller-only, once-only changed transport; never a planning approval."""
import json
try:
    import technical_remediation_plan as plans
except ImportError:
    from broker import technical_remediation_plan as plans

OLD_PROXY='sha256:88a90cbcf03c70dd09fb18a19bf1b65c1dc520867648541b26ca3b84f3e06cad'


def isolated_mounts(info):
    return (not any(m.get('Type')!='tmpfs' or m.get('Destination')!='/opt/data' for m in info.get('Mounts',[]))
            and info['HostConfig'].get('Tmpfs')=={'/opt/data':'size=1m,mode=0700'})


def qualify(config,state,task,reads,event):
    if (state.get('stage')!='blocked' or state.get('category')!='ValueError'
            or state.get('typed_transport_recovery') or state.get('plan')
            or config.get('original_depth')!=2 or task.get('status')!='failed'
            or task.get('failure_reason')!='agent_error.provider_server_error'
            or task.get('agent_id')!=config['cto'] or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id']
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines']
                   for p in config['required_paths'])
            or event.get('status')!=502 or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='nonterminal_or_non_json_response'
            or event.get('finish_reason')!='stop' or event.get('strict_schema') is not True
            or event.get('decision_schema')!='delivery_decision_v1'
            or type(event.get('tool_count')) is not int or event['tool_count']<0):
        raise ValueError('exact unused failed plain-JSON planning transport required')


def capture(b,source):
    """Read authentic live proxy logs before replacing the old image."""
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            c,s=map(json.loads,row)
            if s.get('transport_failure_evidence'):return s['transport_failure_evidence']
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle capture required')
        fx=plans.Effects(b)
        runs=plans.native.issue_task_runs(fx.settings,s['issue_id'])
        if len(runs)!=1:raise ValueError('one original failed planning task required')
        task=fx.task(runs[0]['id'],c['cto']);reads=fx.reads(task)
        with b.db() as con:
            bindings=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(task['id'],)).fetchall()
            if len(bindings)!=1:raise ValueError('one failed execution binding required')
            execution=bindings[0][0]
            if con.execute('SELECT status FROM leases WHERE request_id=?',(execution,)).fetchone()[0]!='closed':
                raise ValueError('closed failed lease required')
        info=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        labels=info['Config'].get('Labels',{})
        if (info['Image']!=OLD_PROXY or labels.get('com.docker.compose.project')!=b.PREFIX
                or labels.get('com.docker.compose.service')!='model-proxy'):
            raise ValueError('original owned proxy required')
        events=[]
        for line in b.docker_stdout(b.PREFIX+'-model-proxy-1',limit=2*1024*1024).splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('execution_id')==execution and e.get('status')==502:events.append(e)
        if len(events)!=1:raise ValueError('one correlated proxy rejection required')
        event={k:events[0].get(k) for k in ('execution_id','call','route','status','category','finish_reason',
            'strict_schema','decision_schema','tool_count','structured_rejection_category')}
        qualify(c,s,task,reads,event)
        proof=dict(operation='preserved_plain_json_remediation_failure_v1',source=source,task=task['id'],
            execution=execution,proxy_image=OLD_PROXY,event=event,reads=reads,
            failed_wakeup=s['wakeup_id'],execution_authorized=False,delivery_approval=False)
        updated={**s,'transport_failure_evidence':proof}
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:
                raise ValueError('planning state changed')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return proof


def recover(b,source,canary_name):
    """Consume a fixed isolated installed-proxy canary, retaining the failure."""
    import remediation_transport_probe as probe
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            c,s=map(json.loads,row)
            review=bool(s.get('review_format_failure'))
            if s.get('review_format_recovery') or (s.get('typed_transport_recovery') and not review):return s
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle changed transport recovery required')
        proof=s.get('review_format_failure' if review else 'transport_failure_evidence') or {}
        fx=plans.Effects(b);task=fx.task(proof['task'],c['reviewer' if review else 'cto'])
        (qualify_review if review else qualify)(c,s,task,fx.reads(task),proof['event'])
        if review:
            original=fx.task(s['plan_task'],c['cto'])
            if not plans.validate_result(c,{**s,'stage':'awaiting_plan','wakeup_id':s['plan_wakeup']},
                    original,fx.result(original),fx.reads(original)) or fx.result(original)!=s['plan']:
                raise ValueError('accepted original CTO plan drift')
        info=b.docker('GET','/containers/'+canary_name+'/json')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        image=b.docker('GET','/images/'+proxy['Image']+'/json')
        labels=info['Config'].get('Labels',{})
        host=info['HostConfig']
        if (info['Image']!=proxy['Image'] or proxy['Image']==proof['proxy_image'] or not proxy['State']['Running']
                or labels.get('com.docker.compose.project')!=b.PREFIX+'-tests'
                or labels.get('com.docker.compose.service')!='remediation-transport-canary'
                or info['Config'].get('Entrypoint')!=['python']
                or info['Config'].get('Cmd')!=['/remediation_transport_probe.py']
                or info['Config'].get('User')!='10000:10000'
                or not isolated_mounts(info)
                or host.get('NetworkMode')!='none' or not host.get('ReadonlyRootfs')
                or host.get('Privileged') or host.get('Binds') or host.get('Devices')
                or info['State'].get('Running') or info['State'].get('ExitCode')!=0
                or info['Config'].get('Env',[])!=image['Config'].get('Env',[])
                or any(any(word in e.split('=',1)[0].upper() for word in ('TOKEN','SECRET','KEY','PASSWORD'))
                       for e in info['Config'].get('Env',[]))):
            raise ValueError('fixed credential-free isolated proxy canary required')
        actual=json.loads(b.docker_stdout(canary_name))
        if actual!=probe.run():raise ValueError('installed typed code qualification drift')
        if review and actual.get('reason_only_feedback_qualified') is not True:raise ValueError('fixed format canary required')
        receipt=dict(operation='changed_review_reason_transport_v1' if review else 'changed_typed_remediation_transport_v1',previous=s,canary=actual,
                     proxy_image=proxy['Image'],execution_authorized=False,revision_depth_reset=False)
        updated={**s,'stage':'review_dispatch' if review else 'plan_dispatch',
                 'review_format_recovery' if review else 'typed_transport_recovery':receipt,'owner':c['reviewer' if review else 'cto']}
        if review:updated['review_protocol']='typed-remediation-bounded-reason-v1'
        for k in ('wakeup_id','dispatched_at','category','required_action'):updated.pop(k,None)
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:
                raise ValueError('planning state changed')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return updated


def qualify_review(config,state,task,reads,event):
    if (state.get('stage')!='blocked' or state.get('category')!='ValueError'
            or state.get('review_format_recovery') or state.get('review_task')
            or not state.get('plan_task') or not state.get('plan_sha256')
            or plans.digest(state.get('plan'))!=state['plan_sha256']
            or config.get('original_depth')!=2 or task.get('status')!='failed'
            or task.get('failure_reason')!='agent_error.provider_server_error'
            or task.get('agent_id')!=config['reviewer'] or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id']
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in config['required_paths'])
            or event.get('status')!=502 or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='typed_schema_maxLength'
            or event.get('decision_rejection_persisted') is not True or event.get('finish_reason')!='tool_calls'
            or event.get('tool_count')!=1):
        raise ValueError('exact unused bounded-reason independent review failure required')


def capture_review(b,source):
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            c,s=map(json.loads,row)
            if s.get('review_format_failure'):return s['review_format_failure']
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle review capture required')
        fx=plans.Effects(b);runs=plans.native.issue_task_runs(fx.settings,s['issue_id'])
        matches=[t for t in runs if t.get('wakeup_id')==s['wakeup_id']]
        if len(matches)!=1 or any(t['status'] in ('queued','running') for t in runs):raise ValueError('one idle failed review required')
        task=fx.task(matches[0]['id'],c['reviewer']);reads=fx.reads(task)
        with b.db() as con:
            bindings=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(task['id'],)).fetchall()
            if len(bindings)!=1:raise ValueError('one review execution required')
            execution=bindings[0][0]
            if con.execute('SELECT status FROM leases WHERE request_id=?',(execution,)).fetchone()[0]!='closed':raise ValueError('closed review required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if proxy['Image']!='sha256:dc6d026767e7798823b9e662665aea427c526db7fa6b1309ff0901d77b3313df':raise ValueError('original review proxy required')
        events=[]
        for line in b.docker_stdout(b.PREFIX+'-model-proxy-1',limit=2097152).splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('execution_id')==execution and e.get('status')==502:events.append(e)
        if len(events)!=1:raise ValueError('one correlated review rejection required')
        event={k:events[0].get(k) for k in ('execution_id','status','category','structured_rejection_category',
                                          'decision_rejection_persisted','finish_reason','tool_count')}
        qualify_review(c,s,task,reads,event)
        proof=dict(operation='preserved_review_reason_format_failure_v1',task=task['id'],execution=execution,
                   proxy_image=proxy['Image'],event=event,reads=reads,plan_sha256=s['plan_sha256'],approval=False)
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:raise ValueError('review state changed')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps({**s,'review_format_failure':proof},sort_keys=True),source))
        return proof
