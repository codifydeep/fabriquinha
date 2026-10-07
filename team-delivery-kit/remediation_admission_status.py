"""Read-only admission status -> idempotent native card metadata.

Display metadata is never execution authority. Delivery and admission state
remain in their controllers; failure to publish cannot stop either workflow.
"""
import json
import inspect
from pathlib import Path
import re
from portable_remediation_intake import read,digest
from release_eval import command as default_command,save_receipt

def select_current(records):
    """Select the unique lineage leaf, never a timestamp or display status."""
    if not records:return None
    nodes={r['intent']['source_task']:r for r in records}
    if len(nodes)!=len(records):raise ValueError('duplicate admission source')
    parents={}
    for key,record in nodes.items():
        predecessors=[other for other,candidate in nodes.items() if
            record['source_issue'] in candidate['phase_issues']]
        if len(predecessors)>1 or key in predecessors:
            raise ValueError('ambiguous admission lineage')
        parents[key]=predecessors[0] if predecessors else None
    leaves=set(nodes)-{p for p in parents.values() if p}
    if len(leaves)!=1:raise ValueError('ambiguous current root admission')
    key=next(iter(leaves));visited=set();cursor=key
    while cursor is not None:
        if cursor in visited:raise ValueError('cyclic admission lineage')
        visited.add(cursor);cursor=parents[cursor]
    if visited!=set(nodes):raise ValueError('disconnected admission lineage')
    return nodes[key]


QUERY='''import sys,json;sys.path.insert(0,"/")
import broker as b,r3_incident_native
from technical_remediation_plan import digest as contract_digest
'''+inspect.getsource(select_current)+'''
with b.db() as con:
 exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_admissions'").fetchone()
 rows=con.execute('SELECT intent,state FROM remediation_admissions').fetchall() if exists else []
 matches=[]
 for raw_intent,raw_state in rows:
  intent,state=json.loads(raw_intent),json.loads(raw_state)
  if intent.get('root_issue')!=sys.argv[1]:continue
  execution=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(intent['source_task'],)).fetchone()
  if not execution:raise ValueError('admission execution missing')
  contract,parent=json.loads(execution[0]),json.loads(execution[1])
  if contract.get('root_issue')!=intent['root_issue'] or contract_digest(contract)!=intent.get('execution_contract_sha256'):
   raise ValueError('admission contract identity drift')
  matches.append(dict(intent=intent,state=state,source_issue=contract['source_issue'],
   phase_issues=[step['issue_id'] for step in parent.get('steps',{}).values() if step.get('issue_id')]))
 current=select_current(matches)
 result=None
 if current:
  intent,state=current['intent'],current['state']
  result=dict(root_issue=intent['root_issue'],stage=state['stage'],
   remaining_calls=r3_incident_native.request('remaining',{},broker=b),
   required_calls=state.get('required_calls',intent['minimum_calls']),
   next_step=state.get('next_step'),owner=state.get('owner','controller'),release_homologated=False)
print(json.dumps(result))
'''


def project(private,root,cli,*,instance='delivery-kit-port2',command=default_command):
    if not isinstance(root,str) or not re.fullmatch('[A-Za-z0-9-]{1,64}',root):raise ValueError('exact root identity required')
    value=json.loads(command('docker','exec',instance+'-execution-broker-1','python','-c',QUERY,root))
    if value is None:return None
    keys={'root_issue','stage','remaining_calls','required_calls','next_step','owner','release_homologated'}
    if (not isinstance(value,dict) or set(value)!=keys or value['root_issue']!=root
            or value['stage'] not in ('awaiting_budget','awaiting_dependency','awaiting_capacity','phases_admitted','blocked')
            or value['next_step'] not in (None,'R1','R2') or value['owner'] not in ('controller','techlead')
            or value['release_homologated'] is not False
            or any(type(value[k]) is not int or not 0<=value[k]<=1000000 for k in ('remaining_calls','required_calls'))):
        raise ValueError('bounded nonauthorizing admission status required')
    private=Path(private);directory=private/'admission-status'
    if private.is_symlink() or not private.is_dir() or directory.is_symlink():raise ValueError('private status storage required')
    directory.mkdir(mode=0o700,exist_ok=True);path=directory/(root+'.json')
    encoded=json.dumps(value,sort_keys=True,separators=(',',':'))
    intent=dict(stage='pending',projection=value,projection_sha256=digest(value),release_homologated=False)
    if path.exists() or path.is_symlink():read(path)  # Reject unsafe previous artifacts.
    save_receipt(path,intent)
    try:
        current=cli('metadata','list',root)
        if current.get('remediation_admission_status')!=encoded:
            cli('metadata','set',root,'--key','remediation_admission_status','--value',encoded,'--type','string')
        result={**intent,'stage':'published'}
    except Exception:
        # Persist only a bounded status, never raw API errors or credentials.
        result=intent
    save_receipt(path,result);return result
