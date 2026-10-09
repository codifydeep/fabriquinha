"""One changed curation attempt from correlated closed native schema rejection."""
import copy
import json
import re
import subprocess


def qualify(state,runs,binding,events,reviewer):
    if (state.get('stage')!='blocked' or state.get('category')!='native_curator_failed'
            or state.get('format_recovery') or len(runs)!=1):return None
    run=runs[0]
    if (run.get('status')!='failed' or run.get('agent_id')!=reviewer
            or binding.get('task_id')!=run.get('id') or binding.get('agent_id')!=reviewer
            or binding.get('issue_id')!=state.get('issue_id') or binding.get('mode')!='planning'
            or binding.get('lease_status')!='closed' or ':planning:' not in binding.get('scope','')):return None
    matched=[e for e in events if e.get('event')=='model_proxy_request'
             and e.get('execution_id')==binding.get('request_id')]
    if len(matched)!=1:return None
    event=matched[0];detail=event.get('structured_rejection_diagnostic') or {}
    if (event.get('status')!=502 or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='schema_violation'
            or event.get('structured_format')!='json_schema' or event.get('strict_schema') is not True
            or event.get('tool_count')!=0 or event.get('finish_reason')!='stop'
            or type(event.get('call_number')) is not int
            or detail.get('version')!='structured-constraint-v1' or detail.get('constraints')!=['maxLength']
            or not re.fullmatch(r'[a-f0-9]{64}',detail.get('upstream_sha256',''))):return None
    result=copy.deepcopy(state)
    result['format_recovery']={'prior_failure':copy.deepcopy(state),'task_id':run['id'],
        'execution_id':binding['request_id'],'call_number':event['call_number'],
        'diagnostic':detail,'attempt_limit':1,'delivery_approval':False,'source_restarted':False}
    result.pop('issue_id',None);result.pop('category',None)
    result['stage']='format_recovery_intent'
    return result


def observe(state,reviewer,namespace,cli):
    if state.get('format_recovery') or state.get('category')!='native_curator_failed':return None
    runs=cli('runs',state['issue_id'])
    if len(runs)!=1 or runs[0].get('status')!='failed' or not re.fullmatch(r'[a-f0-9-]{36}',runs[0].get('id','')):return None
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('owned recovery instance required')
    broker=namespace+'-execution-broker-1';proxy=namespace+'-model-proxy-1'
    for name,service in ((broker,'execution-broker'),(proxy,'model-proxy')):
        labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True,timeout=10))
        if labels.get('com.docker.compose.project')!=namespace or labels.get('com.docker.compose.service')!=service:
            raise ValueError('owned memory recovery service required')
    program='''import broker as b,json,sys
with b.db() as c:
 rows=c.execute("SELECT n.task_id,n.agent_id,n.issue_id,n.scope,n.request_id,g.mode,l.status AS lease_status FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) WHERE n.task_id=?",(sys.argv[1],)).fetchall()
 print(json.dumps([dict(r) for r in rows]))
'''
    rows=json.loads(subprocess.check_output(['docker','exec','-w','/',broker,'python','-c',program,runs[0]['id']],text=True,timeout=15))
    if len(rows)!=1:return None
    raw=subprocess.check_output(['docker','logs','--tail','500',proxy],text=True,timeout=15)
    events=[]
    for line in raw.splitlines():
        try:events.append(json.loads(line))
        except ValueError:continue
    return qualify(state,runs,rows[0],events,reviewer)
