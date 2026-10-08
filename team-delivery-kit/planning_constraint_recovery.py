"""One changed planning attempt, only after an exact correlated schema rejection."""
import json
import subprocess


def pending(state,configuration_sha,registry,cli):
    if state.get('configuration_sha256')!=configuration_sha:return False
    return observe(state,registry,cli) is not None


def revise(state, runs, binding, events, agent_id):
    role=state.get('active')
    if (state.get('stage')!='blocked' or role not in ('product','cto','techlead')
            or not state.get('configuration_sha256') or state.get('schema_'+str(role))
            or state.get('constraint_recovery') or len(runs)!=1):return None
    run=runs[0]
    if (run.get('status')!='failed' or run.get('agent_id')!=agent_id
            or run.get('failure_reason')!='agent_error.provider_server_error'
            or state.get('category')!='RuntimeError:planning agent task failed: '+run['id']
            or binding.get('task_id')!=run['id'] or binding.get('agent_id')!=agent_id
            or binding.get('issue_id')!=state.get('issues',{}).get(role)
            or ':planning:' not in binding.get('scope','')):return None
    rejected=[e for e in events if e.get('execution_id')==binding.get('request_id')
              and e.get('event')=='model_proxy_request']
    if len(rejected)!=1:return None
    event=rejected[0]
    if (event.get('status')!=502 or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='schema_violation'
            or event.get('structured_format')!='json_schema' or event.get('tool_count')!=0
            or type(event.get('call_number')) is not int):return None
    return {**state,'stage':'schema_recovery_'+role,'schema_'+role:1,
        'rejected_schema_source_issue_id':state['issues'][role],
        'constraint_recovery':{'task_id':run['id'],'execution_id':binding['request_id'],
            'call_number':event['call_number'],'category':'schema_violation',
            'constraint_detail':event.get('structured_rejection_diagnostic'),
            'next_action':'One new strict-schema proposal; original failure preserved',
            'delivery_approved':False}}


def observe(state,registry,cli):
    if (state.get('constraint_recovery') or state.get('stage')!='blocked'
            or not state.get('configuration_sha256')
            or not state.get('category','').startswith('RuntimeError:planning agent task failed:')):return None
    role=state.get('active')
    if role not in registry.get('agents',{}) or state.get('schema_'+str(role)):return None
    agent=registry['agents'][role]
    runs=[r for r in cli('runs',state['issues'][role]) if r.get('agent_id')==agent]
    if len(runs)!=1 or runs[0].get('status')!='failed':return None
    # Fixed local owned services, read-only SQL, bounded log window. Missing
    # correlation/evidence never grants a retry. No upstream content is stored.
    from controller_maintenance_cli import arguments
    from evalctl import PROJECT
    if PROJECT!='delivery-kit-port2':return None
    program='''import broker as b,json,sys
with b.db() as c:
 rows=c.execute("SELECT * FROM native_bindings WHERE task_id=?",(sys.argv[1],)).fetchall()
 print(json.dumps([dict(r) for r in rows]))
'''
    # arguments validates the namespace; ownership labels are checked separately.
    broker=arguments(PROJECT,'status','')[4]
    for name,service in ((broker,'execution-broker'),(PROJECT+'-model-proxy-1','model-proxy')):
        labels=json.loads(subprocess.check_output(['docker','inspect','--format',
            '{{json .Config.Labels}}',name],text=True,timeout=10))
        if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service:
            raise ValueError('owned planning recovery services required')
    bindings=json.loads(subprocess.check_output(['docker','exec','-w','/',broker,'python','-c',
        program,runs[0]['id']],text=True,timeout=15))
    if len(bindings)!=1:return None
    raw=subprocess.check_output(['docker','logs','--tail','500',PROJECT+'-model-proxy-1'],
        text=True,timeout=15)
    events=[]
    for line in raw.splitlines():
        try:events.append(json.loads(line))
        except json.JSONDecodeError:continue
    # Maintenance may replace the proxy container. An operator-only archive
    # of its observed event can preserve correlation, never add missing detail.
    from bootstrap_multica import PRIVATE
    archived=PRIVATE/'proxy-observations'/(bindings[0]['request_id']+'.json')
    if archived.exists():
        if (archived.is_symlink() or not archived.is_file()
                or archived.stat().st_mode & 0o077 or archived.stat().st_size>8192):
            raise ValueError('unsafe archived proxy observation')
        event=json.loads(archived.read_text())
        if event not in events:events.append(event)
    return revise(state,runs,bindings[0],events,agent)
