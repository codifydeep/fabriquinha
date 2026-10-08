"""Resume observation of a verified new review, not delivery or author execution."""
import json
import subprocess
from provider_diagnosis_supervision import resume as shared_resume

PROGRAM='''import broker as b,json,native,sys,provider_diagnosis_recovery as r
issue=sys.argv[1]
with b.db() as c:
 row=c.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
 if not row:print('null');sys.exit()
 config,state=map(json.loads,row);proof=state.get('provider_schema_recovery') or {};q=proof.get('qualification') or {}
 if not q:print('null');sys.exit()
 stored=c.execute('SELECT proof FROM provider_review_qualifications WHERE execution_id=?',(q.get('execution_id'),)).fetchone()
 route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
 red=json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
 valid=(config.get('initial_review') is True and route.get('enabled') is True and route['author']!=config['reviewer']
  and state.get('status') in ('awaiting_review','approved') and state.get('wakeup_id')!=proof.get('failed_wakeup')
  and state.get('manifest_sha256')==proof.get('manifest_sha256')==red['red']['manifest_sha256']
  and state.get('source_task')==red['task_id'] and state.get('candidate_volume')==red['volume']
  and proof.get('approval') is False and proof.get('author_restarted') is False
  and stored and json.loads(stored[0])==q and q.get('proxy_image')==r.proxy_info(b)['Image'])
 if not valid:print('null');sys.exit()
s=json.loads((b.STATE/'native.json').read_text());runs=native.issue_task_runs(s,issue)
tasks=[t for t in runs if t.get('wakeup_id')==state.get('wakeup_id') and t.get('agent_id')==config['reviewer']]
if len(tasks)!=1:print('null');sys.exit()
t=tasks[0];valid=t['status'] in ('queued','dispatched','running','completed')
if state['status']=='approved':valid=valid and t['status']=='completed' and state.get('review_task')==t['id']
print(json.dumps({'qualified':bool(valid),'issue_id':issue,'contract_sha256':route['contract_sha256'],
 'independent':True,'recovery_sha256':r.digest(proof),'task_id':t['id'],
 'delivery_approval':False,'author_retry_authorized':False}))
'''


def read_proof(context):
    from evalctl import PROJECT
    name=PROJECT+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned review observer target required')
    return json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',PROGRAM,
        context['issue_id']],text=True,timeout=30))


def resume(ledger,plan,private,*,query=read_proof):
    return shared_resume(ledger,plan,private,query=query,
        category='RuntimeError:test_revision_blocked:invalid_independent_test_review:ValueError',
        record_key='provider_review_supervision')
