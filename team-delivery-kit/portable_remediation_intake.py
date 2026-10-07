"""Prepare a controller-only R3 run from an exact broker-qualified R2 delivery.

No new issue, worker, test revision, merge or deployment is created here.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from execution_context import validate as validate_context,reference
from portable_run_spec import validate as validate_spec
from release_eval import save_receipt

GATES={'independent_review_exact_sha','product_pr','ci_exact_sha','merge',
       'deploy_exact_sha','browser_qa_exact_sha'}


def digest(value):
    """Portable contract/run identity uses the existing ASCII-escaped encoding."""
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def execution_digest(value):
    """Broker recovery contracts retain their distinct UTF-8 canonical encoding."""
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

CANDIDATE_QUERY = '''import sys;sys.path.insert(0,"/")
import broker as b,json
matches=[]
with b.db() as con:
 exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone()
 if exists:
  for raw,state_raw in con.execute('SELECT contract,state FROM remediation_executions'):
   value,state=json.loads(raw),json.loads(state_raw)
   if value.get('root_issue')!=sys.argv[1]:continue
   issue=state.get('steps',{}).get('R2',{}).get('issue_id')
   if not issue:continue
   row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
   handoff=con.execute('SELECT stage FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC,rowid DESC LIMIT 1',(issue,)).fetchone()
   if row and json.loads(row[0]).get('enabled') is True and handoff and handoff[0]=='approved':
    matches.append(issue)
if len(matches)>1:raise ValueError('ambiguous R3 recovery candidate')
print(json.dumps(matches[0] if matches else None))
'''

INPUT_QUERY = '''import sys;sys.path.insert(0,"/")
import broker as b,json,remediation_delivery
from technical_remediation_plan import digest
with b.LOCK:
 proof=remediation_delivery.qualified(b,sys.argv[1],json.loads(sys.argv[2]))
 with b.db() as con:
  row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(proof['source_task'],)).fetchone()
  route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(sys.argv[1],)).fetchone()
  if not row or not route_row:raise ValueError('R3 binding missing')
  value,state=json.loads(row[0]),json.loads(row[1])
  if digest(value)!=proof['execution_contract_sha256'] or state.get('steps',{}).get('R2',{}).get('issue_id')!=sys.argv[1]:
   raise ValueError('R3 binding changed')
  inputs=dict(operation='remediation_r3_input_v1',execution=value,proof=proof,route=json.loads(route_row[0]),release_homologated=False)
print(json.dumps(inputs))
'''


def candidate(command,instance,root_issue):
    """Only a real approved handoff is a candidate, never a worker's text."""
    result=json.loads(command('docker','exec',instance+'-execution-broker-1','python','-c',
                              CANDIDATE_QUERY,root_issue))
    if result is not None and (not isinstance(result,str) or not result or result==root_issue):
        raise ValueError('invalid R3 candidate identity')
    return result


def read_input(command,instance,issue,delivery):
    """Private full context stays off logs; live qualification precedes export."""
    return json.loads(command('docker','exec',instance+'-execution-broker-1','python','-c',
                             INPUT_QUERY,issue,json.dumps(delivery,sort_keys=True)))


def bundle(parent,spec,contract,inputs):
    value=inputs.get('execution',{});proof=inputs.get('proof',{});route=inputs.get('route',{})
    delivery=proof.get('delivery',{});steps=value.get('steps',[])
    if (inputs.get('operation')!='remediation_r3_input_v1' or inputs.get('release_homologated') is not False
            or value.get('version')!='remediation_execution_contract_v1' or len(steps)!=3
            or steps[2].get('id')!='R3' or steps[2].get('depends_on')!=['R2']
            or steps[2].get('edit_scope')!='controller_only' or steps[2].get('owner')!='controller'
            or steps[2].get('editable_files')!=[] or set(steps[2].get('gates',[]))!=GATES
            or value.get('original_depth')!=2 or proof.get('original_depth')!=value.get('original_depth')
            or value.get('release_homologated') is not False
            or value.get('root_issue')!=parent.get('issue_id')
            or value.get('base',{}).get('base_sha')!=parent.get('base_sha')
            or not re.fullmatch('[0-9a-f]{40}',str(parent.get('base_sha','')))
            or value.get('contract_sha256')!=digest(contract)
            or parent.get('contract_sha256')!=digest(contract)
            or parent.get('run_spec_sha256')!=digest({k:v for k,v in spec.items() if k!='sha256'})
            or parent.get('label')!=spec.get('label') or parent.get('durable_handoffs') is not True
            or proof.get('operation')!='qualified_remediation_r2_delivery_v1'
            or proof.get('execution_contract_sha256')!=execution_digest(value)
            or proof.get('source_task')!=value.get('source_task') or proof.get('run_id')!=value.get('run_id')
            or proof.get('issue_id') in (None,parent.get('issue_id'),proof.get('red_origin_issue'))
            or proof.get('release_homologated') is not False
            or set(delivery)!={'source_task','review_task','author','reviewer','manifest_sha256','volume'}
            or delivery.get('source_task') in (None,proof.get('red_origin_task'))
            or route.get('issue_id')!=proof.get('issue_id') or route.get('enabled') is not True
            or route.get('author')!=delivery.get('author') or route.get('reviewer')!=delivery.get('reviewer')
            or not delivery.get('author') or delivery.get('author')==delivery.get('reviewer')):
        raise ValueError('exact original scope and qualified R2 for controller-only R3 required')
    capsule=validate_context(route['execution_context'])
    if route.get('review_instruction')!=reference(capsule,'review'):
        raise ValueError('exact immutable R2 review context required')
    selected={k:v for k,v in spec.items() if k!='sha256'}
    label='REMEDIATION'+digest(dict(source=value['source_task'],run=value['run_id']))[:16].upper()+'-1'
    selected.update(label=label,title=label+' — reviewed R2 publication and same-SHA QA',
        execution_context=capsule,description=reference(capsule,'implementation'),
        review_instruction=reference(capsule,'review'))
    validate_spec(selected,contract)
    context=dict(label=label,issue_id=proof['issue_id'],base_sha=parent['base_sha'],
        contract_sha256=parent['contract_sha256'],run_spec_sha256=digest(selected),durable_handoffs=True,
        remediation_parent=dict(parent),remediation_expected=dict(proof))
    return dict(operation='prepared_remediation_r3_bundle_v1',spec=selected,context=context,
        original_depth=value['original_depth'],execution_authorized=False,release_homologated=False)


def read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>524288:
        raise ValueError('unsafe R3 preparation artifact')
    return json.loads(path.read_text())


def prepare(private,value):
    """Persist intent first; interrupted preparation may finish identical files."""
    private=Path(private)
    if private.is_symlink() or not private.is_dir():raise ValueError('private controller directory required')
    label=value['context']['label']
    if (value.get('operation')!='prepared_remediation_r3_bundle_v1'
            or not re.fullmatch(r'REMEDIATION[A-F0-9]{16}-1',label)
            or value.get('execution_authorized') is not False or value.get('release_homologated') is not False):
        raise ValueError('non-executable R3 preparation bundle required')
    directory=private/'remediation-publication'
    if directory.is_symlink():raise ValueError('unsafe R3 preparation directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    paths=dict(intent=directory/(label+'.json'),spec=directory/(label+'.run.json'),
               context=private/('portable-context-'+label+'.json'))
    descriptor=os.open(directory/(label+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        intent=dict(stage='preparation_intent',bundle=value,bundle_sha256=digest(value),
                    execution_authorized=False,release_homologated=False)
        if paths['intent'].exists() or paths['intent'].is_symlink():
            previous=read(paths['intent'])
            if previous not in (intent,{**intent,'stage':'prepared'}):
                raise ValueError('immutable R3 preparation intent drift')
        else:save_receipt(paths['intent'],intent)
        for name,expected in (('spec',value['spec']),('context',value['context'])):
            if paths[name].exists() or paths[name].is_symlink():
                if read(paths[name])!=expected:raise ValueError('immutable R3 preparation artifact drift')
            else:save_receipt(paths[name],expected)
        save_receipt(paths['intent'],{**intent,'stage':'prepared'})
    return paths
