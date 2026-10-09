"""Resolve an owned proxy pause after operator-authorized provider remediation.

Uses official read-only balance/key endpoints inside the proxy. Never prints a
key, purchases credits, changes a limit, resets a counter, or calls a model.
Run only while the controller is sealed and workers are idle.
"""
import argparse
import json
import re
import subprocess
import uuid

PROGRAM = r'''
import sys,json,os,time,uuid,urllib.request
from pathlib import Path
import model_proxy as m
operation=sys.argv[1]
key=Path('/secret/openrouter.key').read_text().strip()
def official(endpoint):
 r=urllib.request.Request('https://openrouter.ai/api/v1/'+endpoint,headers={'Authorization':'Bearer '+key})
 with urllib.request.urlopen(r,timeout=20) as response:return json.load(response)['data']
credits=official('credits');info=official('key')
if not credits['total_credits']>credits['total_usage'] or not isinstance(info.get('limit_remaining'),(int,float)) or not info['limit_remaining']>0:
 raise ValueError('provider account balance and key allowance must both be positive')
pause=m.provider_pause();calls=m.load_calls();directory=Path(m.COUNTER_PATH).parent
resolved=directory/('provider-resolution-'+operation+'.json')
if resolved.exists():
 if resolved.is_symlink() or resolved.stat().st_size>4096:raise ValueError('unsafe resolution receipt')
 receipt=json.loads(resolved.read_text())
 if receipt['operation_id']!=operation or receipt['operation']!='operator_provider_access_resolution_v1' or receipt['calls_after']!=calls:raise ValueError('resolution counter or identity changed')
else:
 if not pause or pause['call_number']!=calls:raise ValueError('exact paused counter required')
 receipt=dict(operation='operator_provider_access_resolution_v1',operation_id=operation,
  pause=pause,calls_before=calls,calls_after=calls,account_balance_positive=True,
  key_remaining_positive=True,delivery_approval=False,resolved_at=time.time())
 for path,value in ((directory/('provider-pause-resolved-'+operation+'.json'),pause),(resolved,receipt)):
  if path.exists():
   if path.is_symlink() or path.stat().st_size>4096 or json.loads(path.read_text())!=value:raise ValueError('resolution archive drift')
   continue
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
 fd=os.open(directory,os.O_RDONLY);os.fsync(fd);os.close(fd)
if pause:
 if pause!=receipt['pause'] or m.load_calls()!=calls:raise ValueError('pause changed during resolution')
 Path(m.COUNTER_PATH).with_name('provider-pause.json').unlink()
 fd=os.open(directory,os.O_RDONLY);os.fsync(fd);os.close(fd)
print(json.dumps(receipt,sort_keys=True))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True)
    parser.add_argument('--operation',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',args.namespace):
        raise ValueError('exact owned namespace required')
    if str(uuid.UUID(args.operation))!=args.operation:raise ValueError('canonical operation required')
    broker=args.namespace+'-execution-broker-1'
    proxy=args.namespace+'-model-proxy-1'
    for name,service in ((broker,'execution-broker'),(proxy,'model-proxy')):
        labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True))
        if labels.get('com.docker.compose.project')!=args.namespace or labels.get('com.docker.compose.service')!=service:
            raise ValueError('owned Compose services required')
    check='''import broker as b,controller_maintenance as m,json
with b.db() as c:
 state=m.current(c)
 assert state and state['stage']=='sealed' and state.get('drained') is True
 assert state['operation_id']==__import__('sys').argv[1]
 assert not c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
assert not m.native_active(b)
print('sealed-idle')'''
    subprocess.check_output(['docker','exec','-w','/',broker,'python','-c',check,args.operation],text=True)
    result=subprocess.check_output(['docker','exec','-i','-w','/',proxy,'python','-c',PROGRAM,args.operation],text=True)
    print(json.dumps(json.loads(result),sort_keys=True))


if __name__=='__main__':main()
