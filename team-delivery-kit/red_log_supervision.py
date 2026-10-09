"""Refresh a host blocker only from the same controller-validated Red receipt."""
import json
import re
import subprocess


def qualify(status,context,proof):
    return (bool(status) and status.get('stage')=='escalation_required'
        and status.get('category')=='technical_decision_required:RuntimeError:validator output unavailable'
        and status.get('issue_id')==context.get('issue_id')==proof.get('issue_id')
        and proof.get('operation')=='same_red_job_log_recovery_v1'
        and proof.get('stage')=='complete' and proof.get('lease_status')=='closed'
        and proof.get('author_restarted') is False and proof.get('tests_reexecuted') is False
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
    program='''import broker as b,json,sys
with b.db() as c:
 if not c.execute("SELECT 1 FROM sqlite_master WHERE name='red_log_recoveries'").fetchone():print('{}')
 else:
  rows=c.execute("SELECT r.receipt,t.receipt AS red,l.status FROM red_log_recoveries r JOIN test_first_red t ON t.task_id=r.source_task JOIN native_bindings n ON n.task_id=r.source_task JOIN leases l USING(request_id) WHERE t.issue_id=?",(sys.argv[1],)).fetchall()
  if len(rows)!=1:print('{}')
  else:
   r=rows[0];proof=json.loads(r['receipt']);proof.update(lease_status=r['status'],red_output_sha256=json.loads(r['red'])['red']['output_sha256']);print(json.dumps(proof))
'''
    proof=json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',program,context['issue_id']],text=True,timeout=20))
    return qualify(status,context,proof)
