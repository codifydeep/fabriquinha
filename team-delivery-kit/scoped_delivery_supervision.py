"""Resume publication observation only from an exact qualified scoped delivery."""
import json
from provider_diagnosis_supervision import resume as shared_resume
import subprocess
import re

PROGRAM='''import broker as b,json,sys,product_scope_delivery as p
context=json.loads(sys.argv[1]);issue=context['issue_id']
with b.db() as c:
 row=c.execute('SELECT h.stage,h.source_task,h.data,r.config FROM delivery_handoffs h JOIN delivery_routes r USING(issue_id) WHERE h.issue_id=? ORDER BY h.updated DESC LIMIT 1',(issue,)).fetchone()
 if not row or row[0]!='approved':print('null');sys.exit()
 route=json.loads(row[3]);data=json.loads(row[2]);review=data.get('review') or {}
 if route.get('enabled') is not True or route.get('contract_sha256')!=context['contract_sha256']:print('null');sys.exit()
 snapshot=c.execute('SELECT volume FROM snapshots WHERE task_id=?',(row[1],)).fetchone()
 if not snapshot or review.get('source_task_id')!=row[1] or review.get('status')!='approved':print('null');sys.exit()
 delivery=dict(source_task=row[1],review_task=review['review_task_id'],author=route['author'],reviewer=review['reviewer_agent_id'],manifest_sha256=review['manifest_sha256'],volume=snapshot[0])
proof=p.qualified(b,issue,delivery)
if not proof or proof['original_contract_sha256']!=context['contract_sha256'] or proof['base_sha']!=context['base_sha']:print('null');sys.exit()
import hashlib
sha=hashlib.sha256(json.dumps(proof,sort_keys=True,separators=(',',':')).encode()).hexdigest()
print(json.dumps(dict(qualified=True,issue_id=issue,contract_sha256=context['contract_sha256'],independent=True,recovery_sha256=sha,task_id=delivery['source_task'],delivery_approval=False,author_retry_authorized=False)))
'''


def read_proof(context):
    from evalctl import PROJECT
    name=PROJECT+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned scope observer target required')
    return json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',PROGRAM,
        json.dumps(context,sort_keys=True)],text=True,timeout=30))


def resume(ledger,plan,private,*,query=read_proof):
    return shared_resume(ledger,plan,private,query=query,
        category='RuntimeError:technical_decision_required:portable frozen suite failed',
        record_key='scoped_delivery_supervision')


def eligible(status,context,*,query=read_proof):
    if (not status or status.get('stage')!='escalation_required'
            or status.get('category')!='technical_decision_required:portable frozen suite failed'
            or status.get('issue_id')!=context.get('issue_id')
            or context.get('durable_handoffs') is not True):return False
    proof=query(context) or {}
    return (proof.get('qualified') is True and proof.get('independent') is True
        and proof.get('issue_id')==context['issue_id']
        and proof.get('contract_sha256')==context['contract_sha256']
        and bool(proof.get('task_id'))
        and re.fullmatch(r'[a-f0-9]{64}',str(proof.get('recovery_sha256',''))) is not None
        and proof.get('delivery_approval') is False and proof.get('author_retry_authorized') is False)
