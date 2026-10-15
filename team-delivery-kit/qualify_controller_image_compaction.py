"""Offline comparison of two explicitly selected controller IMAGEs, never live state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from docker_grouping import args

ROOT=Path(__file__).resolve().parent
UPDATES={'calibration_objection_runtime.py':'broker/calibration_objection_runtime.py',
    'calibration_experiment_runtime.py':'broker/calibration_experiment_runtime.py'}
PROGRAM='''import hashlib,json,pathlib
print(json.dumps({p.name:dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),mode=p.stat().st_mode&511)
 for p in pathlib.Path("/").glob("*.py") if p.is_file()},sort_keys=True))
'''


def require(ok):
    if not ok:raise ValueError('exact controller compaction qualification required')


def compare(old,new,before,after,expected):
    for key in ('Env','User','WorkingDir','Entrypoint','Volumes','ExposedPorts','Healthcheck','StopSignal'):
        require(old.get(key)==new.get(key))
    require((old.get('Cmd') or [])==(new.get('Cmd') or []))
    require(set(before)==set(after) and set(expected)<=set(before))
    for name,record in before.items():
        require(after[name]==({**record,'sha256':expected[name]} if name in expected else record))
    require('broker.py' in before)


def inspect(image):
    require(bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    value=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]
    require(value['Id']==image);return value


def manifest(image):
    command=['docker','run','--rm',*args('controller-image-compaction','delivery-kit-port2'),
        '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','256m','--pids-limit','64','--entrypoint','python',image,'-I','-S','-B','-c',PROGRAM]
    return json.loads(subprocess.check_output(command,timeout=90))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--before',required=True);parser.add_argument('--after',required=True)
    options=parser.parse_args();old,new=map(inspect,(options.before,options.after))
    expected={name:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for name,path in UPDATES.items()}
    before,after=map(manifest,(options.before,options.after));compare(old['Config'],new['Config'],before,after,expected)
    require(len(new['RootFS']['Layers'])<len(old['RootFS']['Layers']))
    print(json.dumps(dict(operation='controller_image_compaction_v1',config_preserved=True,
        root_python_files=len(before),source_updates_verified=sorted(expected),broker_sha256=after['broker.py']['sha256'],
        old_layers=len(old['RootFS']['Layers']),new_layers=len(new['RootFS']['Layers']),
        live_container_exported=False,model_calls=0,delivery_approval=False)))


if __name__=='__main__':main()
