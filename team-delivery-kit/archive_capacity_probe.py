"""Publish controller diagnostic evidence privately, never into product delivery.

No model request, wakeup or approval is issued here. The persistent handoff
controller decides whether the exact current incident may wake its CTO.
"""
import argparse
import json
from pathlib import Path
import subprocess
import uuid
from broker import prospective_capacity as capacity
from evalctl import PRIVATE,PROJECT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execution',required=True)
    args=parser.parse_args();identifier=args.execution
    if PROJECT!='delivery-kit-port2' or str(uuid.UUID(identifier))!=identifier:
        raise ValueError('canonical isolated diagnostic required')
    folder=PRIVATE/'provider-probes'
    if folder.is_symlink():raise ValueError('restricted original evidence required')
    def read(suffix):
        path=folder/('frozen-patch-'+identifier+suffix)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.stat().st_size>262144:
            raise ValueError('bounded private original receipt required')
        return json.loads(path.read_text())
    probe,inputs=read('.json'),read('.input.json')
    if probe.get('execution_id')!=identifier:raise ValueError('exact receipt identity required')
    proof=capacity.validate_proof(probe,inputs,probe['issue_id'],probe['source_task'])
    for service in ('model-proxy','execution-broker'):
        labels=json.loads(subprocess.check_output(['docker','inspect',PROJECT+'-'+service+'-1',
            '--format','{{json .Config.Labels}}'],text=True))
        if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service:
            raise ValueError('owned core services required')
    proxy=PROJECT+'-model-proxy-1'
    image=subprocess.check_output(['docker','inspect',proxy,'--format','{{.Image}}'],text=True).strip()
    if image!=probe.get('proxy_image'):raise ValueError('same owned proxy required')
    ledger_script='''import model_proxy,sqlite3,json,sys
from pathlib import Path
p=Path(model_proxy.COUNTER_PATH).with_name('seed-patch-provider-probes.sqlite')
c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
r=c.execute('SELECT state,receipt FROM probes WHERE id=?',(sys.argv[1],)).fetchone()
assert r and r[0]=='failed';print(r[1]);c.close()
'''
    stored=json.loads(subprocess.check_output(['docker','exec','-w','/',proxy,'python','-c',ledger_script,identifier],text=True))
    if not stored or any(probe.get(k)!=v for k,v in stored.items()):
        raise ValueError('same durable proxy experiment outcome required')
    # Fixed private publication, not an agent-provided tool or command.
    publish='''import broker as b,json,sys,os
from pathlib import Path
import prospective_capacity as capacity
value=json.load(sys.stdin);probe,inputs=value['probe'],value['inputs']
proof=capacity.validate_proof(probe,inputs,probe['issue_id'],probe['source_task'])
folder=b.STATE/'prospective-capacity-evidence';folder.mkdir(mode=0o700,exist_ok=True)
assert not folder.is_symlink() and not folder.stat().st_mode&0o077
def store(path,value):
 encoded=json.dumps(value,sort_keys=True).encode()
 if path.exists():
  assert not path.is_symlink() and not path.stat().st_mode&0o077 and json.loads(path.read_text())==value
  return
 with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
  f.write(encoded);f.flush();os.fsync(f.fileno())
identifier=probe['execution_id']
store(folder/(identifier+'.json'),probe);store(folder/(identifier+'.input.json'),inputs)
store(b.STATE/'prospective-capacity.json',dict(execution_id=identifier))
print(json.dumps(dict(archived=True,execution_id=identifier,probe_sha256=proof['probe_sha256'],
 author_retry_authorized=False,delivery_approval=False)))
'''
    result=subprocess.check_output(['docker','exec','-i','-w','/',PROJECT+'-execution-broker-1',
        'python','-c',publish],input=json.dumps(dict(probe=probe,inputs=inputs)),text=True)
    print(result.strip())


if __name__=='__main__':main()
