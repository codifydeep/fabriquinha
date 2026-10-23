"""Operator-only runtime preflight, never an execution/admission capability.

Only six immutable image selectors and two planning-role identities may change.
No flags, model, credentials, mounts, commands or policy exemptions are inputs.
"""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid
from quality_git_candidate import require
from quality_candidate_authority import Authority

PREFIX='BROKER_QUALITY_'
IMAGES={
    PREFIX+'PREP_IMAGE':('quality-author-prep',['python']),
    PREFIX+'WORKER_IMAGE':('quality-author-worker',['python']),
    PREFIX+'COPY_IMAGE':('quality-red-copy',['python']),
    PREFIX+'RED_IMAGE':('quality-red-observer',['python','/opt/quality/quality_red_observation.py']),
    PREFIX+'REVIEW_WORKER_IMAGE':('quality-author-worker',['python']),
    PREFIX+'GREEN_JOB_IMAGE':('quality-green-job',['python','/opt/quality/quality_green_job.py'])}
ROLES={PREFIX+'TECHLEAD',PREFIX+'CTO'}

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b
s=json.loads((b.STATE/"native.json").read_text())
print(json.dumps(dict(namespace=b.PREFIX,agents=s["agents"],flags=[getattr(b,k,False) is True for k in
 ("QUALITY_V2_ENABLED","QUALITY_REVIEW_ENABLED","QUALITY_IMPLEMENTATION_ENABLED","QUALITY_TEAM_ENABLED")],
 exclusive=getattr(b,"QUALITY_EXCLUSIVE_ENABLED",False) is True),sort_keys=True))
'''


def syntax(value):
    require(isinstance(value,dict) and set(value)==set(IMAGES)|ROLES)
    for key in IMAGES:require(isinstance(value[key],str) and re.fullmatch('sha256:[a-f0-9]{64}',value[key]))
    for key in ROLES:require(isinstance(value[key],str) and str(uuid.UUID(value[key]))==value[key])
    require(value[PREFIX+'TECHLEAD']!=value[PREFIX+'CTO'])
    return dict(value)


def validate(value,metadata,agents):
    value=syntax(value)
    require(isinstance(agents,dict) and all(agents.get(value[key])=='planning' for key in ROLES))
    for key,(component,entrypoint) in IMAGES.items():
        image=metadata.get(value[key]);require(isinstance(image,dict))
        config=image.get('Config',{});labels=config.get('Labels',{})
        require(image.get('Id')==value[key] and config.get('User')=='10000:10000' and not config.get('Volumes')
            and labels.get('delivery-kit.component')==component and config.get('Entrypoint')==entrypoint
            and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
                for v in config.get('Env',[])))
        if component=='quality-author-worker':
            require({'tests_only_v2','test_review_v2','implementation_v2'}<=set(labels.get('delivery-kit.quality-phases','').split(',')))
        if component=='quality-green-job':
            require({'snapshot_after_implementation_v2','observe_green_v2','observe_reversion_v2'}<=
                set(labels.get('delivery-kit.quality-operations','').split(',')))
    return value


def probe(namespace,controller_image,value,*,sealed_upgrade=False):
    value=syntax(value);authority=Authority(namespace,controller_image)
    about=authority.about()
    require(about['maintenance'] is True and (about['v2_enabled'] is False and about['implementation_enabled'] is False
        or sealed_upgrade and about['v2_enabled'] is True and about['implementation_enabled'] is True))
    if sealed_upgrade:
        from qualify_quality_red_observer import require_idle
        require_idle(namespace)  # Sealed/drained plus no native tasks or leases.
    raw=subprocess.check_output(['docker','exec',authority.identity,'python','-c',PROGRAM],text=True,timeout=30)
    require(len(raw.encode())<=65536);native=json.loads(raw)
    require(native['namespace']==namespace and authority.inspect_controller()==authority.identity)
    if sealed_upgrade:
        flags=native.get('flags')
        require(flags in ([False]*4,[True]*4) and all(type(v) is bool for v in flags)
            and flags[0] is about['v2_enabled'] and flags[2] is about['implementation_enabled']
            and (not any(flags) or native.get('exclusive') is True))
    records=json.loads(subprocess.check_output(['docker','image','inspect',*sorted(set(value[k] for k in IMAGES))],text=True,timeout=30))
    return validate(value,{r['Id']:r for r in records},native['agents'])


def load(path):
    path=Path(path);require(path.is_absolute() and path.resolve()==path and path.is_file())
    info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
        and not info.st_mode&0o077 and 0<info.st_size<=65536)
    def unique(pairs):
        require(len({key for key,_ in pairs})==len(pairs));return dict(pairs)
    return syntax(json.loads(path.read_bytes(),object_pairs_hook=unique))
