"""Refresh a host blocker only from the same controller-validated Red receipt."""
import json
import re
import subprocess


def qualify(status,context,proof):
    authority=(proof.get('operation')=='same_red_job_log_recovery_v1'
        and proof.get('author_restarted') is False and proof.get('tests_reexecuted') is False)
    if proof.get('operation')=='cto_corrected_red_log_recovery_v1':
        authority=(proof.get('host_restarted_author') is False and proof.get('cto_authorized') is True
            and proof.get('tests_reexecuted') is True and bool(proof.get('cto_task'))
            and bool(proof.get('source_task')) and bool(proof.get('prior_source_task'))
            and proof['source_task']!=proof['prior_source_task'])
    return (bool(status) and status.get('stage')=='escalation_required'
        and status.get('category')=='technical_decision_required:RuntimeError:validator output unavailable'
        and status.get('issue_id')==context.get('issue_id')==proof.get('issue_id')
        and proof.get('stage')=='complete' and proof.get('lease_status')=='closed'
        and authority
        and proof.get('delivery_approval') is False
        and bool(re.fullmatch(r'[a-f0-9]{64}',proof.get('output_sha256','')))
        and proof.get('output_sha256')==proof.get('red_output_sha256'))


def eligible(status,context):
    if (not status or status.get('category')!='technical_decision_required:RuntimeError:validator output unavailable'
            or status.get('issue_id')!=context.get('issue_id')): return False
    from evalctl import PROJECT
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',PROJECT):return False
    name=PROJECT+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='execution-broker':return False
    program='''import broker as b,json,sys,native
with b.db() as c:
 rows=c.execute("SELECT r.receipt,t.receipt AS red,l.status FROM red_log_recoveries r JOIN test_first_red t ON t.task_id=r.source_task JOIN native_bindings n ON n.task_id=r.source_task JOIN leases l USING(request_id) WHERE t.issue_id=?",(sys.argv[1],)).fetchall() if c.execute("SELECT 1 FROM sqlite_master WHERE name='red_log_recoveries'").fetchone() else []
 if len(rows)!=1:
   proof={};issue=sys.argv[1]
   red=c.execute("SELECT task_id,receipt FROM test_first_red WHERE issue_id=?",(issue,)).fetchone()
   route=c.execute("SELECT config FROM delivery_routes WHERE issue_id=?",(issue,)).fetchone()
   if red and route and json.loads(route[0]).get('enabled') is True:
    config=json.loads(route[0]);settings=json.loads((b.STATE/'native.json').read_text())
    for prior in c.execute("SELECT source_task,data FROM delivery_handoffs WHERE issue_id=?",(issue,)):
     d=json.loads(prior['data'])
     if (d.get('error')!='RuntimeError:validator output unavailable' or d.get('phase')!='test_first'
       or (d.get('decision') or {}).get('action')!='request_correction' or not d.get('cto_task')
       or prior['source_task']==red['task_id']):continue
     task=native.task_record(settings,red['task_id'],config['author']);cto=native.task_record(settings,d['cto_task'],config['cto'])
     lease=c.execute("SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?",(red['task_id'],issue,config['author'])).fetchone()
     if (task['status']=='completed' and cto['status']=='completed' and task.get('issue_id')==issue
       and cto.get('issue_id')==issue and lease and lease[0]=='closed'
       and task.get('wakeup_id')==d.get('test_first_correction_wakeup') and bool(task.get('wakeup_id'))):
      sha=json.loads(red['receipt'])['red']['output_sha256']
      proof=dict(operation='cto_corrected_red_log_recovery_v1',issue_id=issue,stage='complete',lease_status='closed',source_task=red['task_id'],prior_source_task=prior['source_task'],cto_task=d['cto_task'],cto_authorized=True,host_restarted_author=False,tests_reexecuted=True,delivery_approval=False,output_sha256=sha,red_output_sha256=sha)
   print(json.dumps(proof))
 else:
   r=rows[0];proof=json.loads(r['receipt']);proof.update(lease_status=r['status'],red_output_sha256=json.loads(r['red'])['red']['output_sha256']);print(json.dumps(proof))
'''
    proof=json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',program,context['issue_id']],text=True,timeout=20))
    return qualify(status,context,proof)
