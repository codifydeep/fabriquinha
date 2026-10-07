"""Read-only admission status -> idempotent native card metadata.

Display metadata is never execution authority. Delivery and admission state
remain in their controllers; failure to publish cannot stop either workflow.
"""
import json
from pathlib import Path
import re
from portable_remediation_intake import read,digest
from release_eval import command as default_command,save_receipt

QUERY='''import sys,json;sys.path.insert(0,"/")
import broker as b,r3_incident_native
with b.db() as con:
 exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_admissions'").fetchone()
 rows=con.execute('SELECT intent,state FROM remediation_admissions').fetchall() if exists else []
 matches=[(json.loads(i),json.loads(s)) for i,s in rows if json.loads(i).get('root_issue')==sys.argv[1]]
 if len(matches)>1:raise ValueError('ambiguous root admission')
 result=None
 if matches:
  intent,state=matches[0]
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
