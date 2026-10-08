"""Resume a stopped sequence observer only after verified CTO provider recovery."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


PROGRAM='''import broker as b,json,native,sys,provider_diagnosis_recovery as r,handoff_runtime
issue=sys.argv[1]
with b.db() as c:
 if not c.execute("SELECT 1 FROM sqlite_master WHERE name='provider_diagnosis_recoveries'").fetchone():print('null');sys.exit()
 route_row=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
 rows=c.execute('SELECT h.*,p.record FROM delivery_handoffs h JOIN provider_diagnosis_recoveries p USING(source_task) WHERE h.issue_id=?',(issue,)).fetchall()
 if not route_row or len(rows)!=1:print('null');sys.exit()
 route=json.loads(route_row[0]);state=dict(rows[0]);data=json.loads(state['data']);record=json.loads(state['record']);proof=record.get('proof') or {}
 q=proof.get('qualification') or {}
 stored=c.execute('SELECT proof FROM provider_diagnosis_qualifications WHERE execution_id=?',(q.get('execution_id'),)).fetchone()
 latest=c.execute('SELECT stage FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
 verified=(route.get('enabled') is True and route.get('test_first') is True and route['author']!=route['cto']
  and record.get('state')=='accepted' and data.get('provider_diagnosis_recovery')==record
  and proof.get('operation')=='provider_diagnosis_recovery_v1' and proof.get('issue')==issue
  and proof.get('source_task')==state['source_task'] and proof.get('author_retry_authorized') is False
  and proof.get('delivery_approval') is False and stored and json.loads(stored[0])==q
  and proof.get('diagnostic_sha256')==r.digest(data.get('diagnostic'))
  and data.get('test_first_cto_wakeup')==record.get('wakeup_id')
  and q.get('proxy_image')==r.proxy_info(b)['Image'])
 if not verified:print('null');sys.exit()
s=json.loads((b.STATE/'native.json').read_text());runs=native.issue_task_runs(s,issue)
sources=[t for t in runs if t['id']==state['source_task'] and t.get('agent_id')==route['author'] and t.get('status')=='failed']
tasks=[t for t in runs if t.get('wakeup_id')==record['wakeup_id'] and t.get('agent_id')==route['cto']]
if len(sources)!=1 or len(tasks)!=1:print('null');sys.exit()
task=tasks[0]
active=state['stage']=='test_first_cto_diagnosis' and task.get('status') in ('queued','dispatched','running')
decided=(state['stage'] in ('test_first_cto_correction','test_first_cto_correction_wait')
 and task.get('status')=='completed' and data.get('cto_task')==task['id']
 and data.get('decision')==handoff_runtime.Effects(b,s).decision(task)
 and data['decision'].get('action')=='request_correction' and data['decision'].get('optional_files')==[]
 and latest['stage'] not in ('test_first_blocked','technical_decision_required','diagnose_cto'))
print(json.dumps({'qualified':bool(active or decided),'issue_id':issue,'contract_sha256':route['contract_sha256'],
 'independent':True,'recovery_sha256':r.digest(record),'task_id':task['id'],
 'delivery_approval':False,'author_retry_authorized':False}))
'''


def read_proof(context):
    from evalctl import PROJECT
    name=PROJECT+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned recovery observer target required')
    return json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',PROGRAM,
                                              context['issue_id']],text=True,timeout=30))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def resume(ledger,plan,private,*,query=read_proof,
           category='RuntimeError:test_first_blocked:test_first_cto_execution_failed',
           record_key='provider_diagnosis_supervision'):
    labels=[stage['spec']['label'] for stage in plan['stages']];label=ledger.get('active')
    if (ledger.get('stage')!='blocked' or label not in labels or ledger.get('plan_sha256')!=plan['sha256']
            or ledger.get('category')!=category
            or ledger.get('completed')!=labels[:labels.index(label)]):return None
    stage=plan['stages'][labels.index(label)]
    path=Path(private)/('portable-context-'+label+'.json')
    if not path.exists():return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:
        raise ValueError('safe bounded original execution context required')
    context=json.loads(path.read_text())
    if (context.get('issue_id')!=ledger.get('issues',{}).get(label) or context.get('label')!=label
            or context.get('durable_handoffs') is not True
            or context.get('contract_sha256')!=digest(stage['contract'])
            or context.get('run_spec_sha256')!=digest(stage['spec'])):return None
    proof=query(context) or {}
    if (proof.get('qualified') is not True or proof.get('independent') is not True
            or proof.get('issue_id')!=context['issue_id'] or proof.get('contract_sha256')!=context['contract_sha256']
            or proof.get('delivery_approval') is not False or proof.get('author_retry_authorized') is not False
            or not proof.get('task_id') or not re.fullmatch(r'[a-f0-9]{64}',str(proof.get('recovery_sha256','')))):
        return None
    result=dict(ledger,stage='working')
    result[record_key]=dict(category=ledger['category'],proof=proof,delivery_approval=False)
    for field in ('category','owner','next_action','board_notification_error'):result.pop(field,None)
    return result
