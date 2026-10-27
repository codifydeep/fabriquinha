"""Offline Compose bootstrap with a fake credential; retain two tiny proof volumes.

No relay, provider request, real credential, network or preexisting volume edits.
The exact grouped bootstrap/probe containers are synchronous and --rm.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'team-delivery-kit'))
from docker_grouping import args as grouping


def qualify(root,namespace,image):
    root=Path(root).resolve()
    if (root.exists() or not re.fullmatch('delivery-kit-[a-z0-9-]{1,42}',namespace)
            or not re.fullmatch('sha256:[a-f0-9]{64}',image)):
        raise ValueError('fresh private root, owned namespace and cached exact image required')
    if root.is_relative_to(ROOT) and subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet',str(root)],capture_output=True).returncode:
        raise ValueError('proof must be outside public tracked paths')
    def run(args,**kwargs):return subprocess.run(args,capture_output=True,text=True,timeout=60,**kwargs)
    names=[namespace+'-meter',namespace+'-secret']
    existing=set(run(['docker','volume','ls','--format','{{.Name}}'],check=True).stdout.splitlines())
    if existing.intersection(names):raise ValueError('proof volumes already exist; inspect, never reset')
    root.mkdir(parents=True,mode=0o700)
    (root/'policy.json').write_text('{}');(root/'policy.json').chmod(0o600)
    for name in names:
        run(['docker','volume','create','--label','com.docker.compose.project='+namespace+'-tests',
             '--label','fabriquinha.storage-proof='+namespace,name],check=True)
    env={**os.environ,'FABRIQUINHA_INSTANCE':namespace+'-tests','FABRIQUINHA_PYTHON_IMAGE':image,
         'FABRIQUINHA_SOURCE':str(ROOT),'FABRIQUINHA_POLICY':str(root/'policy.json'),
         'FABRIQUINHA_PROVIDER_PORT':'19998','FABRIQUINHA_METER_VOLUME':names[0],
         'FABRIQUINHA_SECRET_VOLUME':names[1],'FABRIQUINHA_PROJECT':'f'*64,
         'FABRIQUINHA_CORE_SUBNET':'10.245.252.32/28'}
    command=['docker','compose','-f',str(ROOT/'examples/python-http/compose.provider.yml'),
             '--profile','bootstrap','run','--rm','-T','--no-deps','storage-bootstrap']
    first=run(command,input='offline-fixture-key\n',env=env)
    (root/'bootstrap.log').write_text(first.stdout+first.stderr);(root/'bootstrap.log').chmod(0o600)
    if first.returncode:raise ValueError('bootstrap failed; inspect private log, do not repeat')
    second=run(command,input='must-not-replace-key\n',env=env)
    if second.returncode==0:raise AssertionError('existing meter was overwritten')
    probe='''import json,os
from pathlib import Path
m=Path('/meter');s=Path('/secret')
assert json.loads((m/'calls.json').read_text())=={'calls':0}
assert (s/'openrouter.key').read_bytes()==b'offline-fixture-key'
assert all(p.stat().st_uid==10000 and p.stat().st_mode&0o077==0 for p in (m,s,m/'calls.json',s/'openrouter.key'))
assert (s/'openrouter.key').stat().st_mode&0o777==0o400
print('storage verified without disclosing credential')
'''
    run(['docker','run','--rm',*grouping('storage-probe',namespace),'--network','none','--read-only',
         '--entrypoint','python','--user','10000:10000','--cap-drop','ALL','--security-opt','no-new-privileges:true',
         '--mount','type=volume,source='+names[0]+',target=/meter,readonly',
         '--mount','type=volume,source='+names[1]+',target=/secret,readonly',image,'-B','-c',probe],check=True)
    result=dict(passed=True,model_calls=0,real_credentials=False,existing_state_refused=True,
                relay_owner_read_verified=True,containers_retired=True,proof_volumes_retained=names)
    (root/'receipt.json').write_text(json.dumps(result,indent=2));(root/'receipt.json').chmod(0o600)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.root,args.namespace,args.image),indent=2))
