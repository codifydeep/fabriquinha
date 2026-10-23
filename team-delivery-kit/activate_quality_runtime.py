"""Activate one fresh qualification while keeping maintenance sealed.

Only five fixed flags may change. Same controller image, credentials, helper
selectors, mounts/resources and every other container remain exact. Requires
the existing install backup, one unexecuted enrollment and an unloaded/disabled
host scheduler. Unknown Compose outcome is observed, never sent twice. This
does not release maintenance, start the proxy, assign an issue or approve it.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import os
import stat
import subprocess
import time
import uuid
import enroll_quality_lifecycle as enrollment
import install_quality_preview as install
from migrate_quality_candidate_pin import Effects as Service,folder,read
from quality_candidate_authority import Authority,Pending
from quality_git_candidate import journal,require
from qualify_quality_red_observer import require_idle

ROOT=Path(__file__).resolve().parent
FLAGS=(*install.FLAGS,'BROKER_QUALITY_EXCLUSIVE_ENABLED')
PROGRAM='''import sys,json,hashlib,pathlib,time
sys.path.insert(0,"/")
import broker as b,native,quality_lifecycle_enrollment as e,quality_execution_isolation as isolation,quality_team_progress as team
settings=json.loads((b.STATE/"native.json").read_bytes());issue=sys.argv[1]
with b.db() as con:
 rows=con.execute("SELECT issue_id FROM quality_lifecycle_enrollments").fetchall()
 assert any(row[0]==issue for row in rows)
 for row in rows:
  if row[0]==issue:continue
  assert e.lookup(con,row[0]) is not None
  previous=con.execute("SELECT task_id FROM quality_author_admissions WHERE issue_id=?",(row[0],)).fetchall()
  assert len(previous)==1
  record=team.load(b,previous[0][0])
  assert record is not None and record[1]["stage"]=="technical_blocked"
 receipt=e.lookup(con,issue)
 pending=con.execute("SELECT count(*) FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.deadline>? AND (g.used=0 OR (g.used=1 AND l.request_id IS NULL))",(time.time(),)).fetchone()[0]
assert receipt and pending==0
if native.issue_task_runs(settings,issue):
 import quality_review_recovery as recovery,quality_test_revision as revision
 if not revision.activation_ready(b,issue,sys.argv[2]):recovery.activation_ready(b,issue,sys.argv[2])
assert settings["agents"].get(receipt["author"])=="implementation" and settings["agents"].get(receipt["reviewer"])=="review"
print(json.dumps(dict(issue_id=issue,enrollment=receipt,source_sha256=hashlib.sha256(pathlib.Path(isolation.__file__).read_bytes()).hexdigest(),exclusive=b.QUALITY_EXCLUSIVE_ENABLED,
 flags=[b.QUALITY_V2_ENABLED,b.QUALITY_REVIEW_ENABLED,b.QUALITY_IMPLEMENTATION_ENABLED,b.QUALITY_TEAM_ENABLED]),sort_keys=True))
'''


def env(info):
    rows=info['Config'].get('Env',[]);value=dict(v.split('=',1) for v in rows)
    require(len(rows)==len(value));return value


def active_sources(files):
    overlay=ROOT/'compose.quality-v2-exclusive.yaml'
    return [*[p for p in files if p!=overlay],overlay]


def verify(before,after):
    original=env(before);actual=env(after)
    require(after['Name']==before['Name'] and all(after['Config']['Labels'].get(k)==before['Config']['Labels'].get(k)
        for k in ('com.docker.compose.project','com.docker.compose.service')))
    require(all(original.get(k)=='0' for k in install.FLAGS) and original.get('BROKER_QUALITY_EXCLUSIVE_ENABLED','0') in ('0','1'))
    require(actual=={**original,**{k:'1' for k in FLAGS}})
    normalized=copy.deepcopy(after);normalized['Config']['Env']=list(before['Config']['Env'])
    install.verify_preservation(before,normalized,before['Image'])


def preflight(namespace,image,payload,*,maintenance_operation=None):
    authority=Authority(namespace,image);about=authority.about()
    require(about['maintenance'] is True and about['v2_enabled'] is False and about['implementation_enabled'] is False)
    maintenance,_=require_idle(namespace)
    barrier=maintenance_operation or payload['maintenance_operation']
    require(maintenance['operation_id']==barrier);Service().stopped(namespace)
    result=json.loads(install.command(['docker','exec',authority.identity,'python','-c',PROGRAM,payload['plan']['issue_id'],barrier]).stdout)
    require(authority.inspect_controller()==authority.identity and type(result['exclusive']) is bool
        and result['flags']==[False]*4 and all(type(v) is bool for v in result['flags'])
        and result['enrollment']['plan_sha256']==enrollment.enrollment.policy.digest(payload['plan'])
        and result['source_sha256']==hashlib.sha256((ROOT/'broker/quality_execution_isolation.py').read_bytes()).hexdigest())
    return authority.identity


def activate(namespace,image,path,pin,operation,install_operation,*,maintenance_operation=None):
    for value in (operation,install_operation):enrollment.enrollment.canonical(value)
    require(re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    payload=enrollment.load(path,pin);private=folder(ROOT/('.local-'+namespace.removeprefix('delivery-kit-')))
    barrier=maintenance_operation or payload['maintenance_operation'];enrollment.enrollment.canonical(barrier)
    archive=folder(folder(private/'backups')/('quality-activation-'+operation))
    identity=dict(namespace=namespace,image=image,payload_pin=pin,operation=operation,install_operation=install_operation)
    if maintenance_operation is not None:identity['maintenance_operation']=maintenance_operation
    token=str(uuid.uuid5(uuid.NAMESPACE_URL,'quality-activation:'+namespace))
    with journal(private,token,family='quality-candidate-dispatch'):
        statefile=archive/'state.json'
        if statefile.exists():
            state=json.loads(read(statefile));require(state['identity']==identity)
            if state['stage'] in ('activated_sealed','technical_blocked'):return state['receipt']
            require(state['stage'] in ('prepared','recreate_intent'))
            before=json.loads(read(archive/'before.json'))
        else:
            current=preflight(namespace,image,payload,maintenance_operation=barrier);before=install.inspect(current)
            backup=private/'backups'/('quality-preview-install-'+install_operation)
            installed=json.loads(read(backup/'state.json'));proof=json.loads(read(backup/'backup-receipt.json'))
            require(installed['stage']=='installed_disabled' and installed['image']==image
                and installed['receipt']['container_id']==current and installed['maintenance_operation']==barrier
                and proof['restore_integrity']=='ok' and proof['backup_integrity']=='ok' and proof['backup_id']==install_operation
                and proof['operation_id']==barrier)
            compressed=backup/'leases.sqlite.gz';info=compressed.stat()
            require(compressed.resolve()==compressed and not compressed.is_symlink() and stat.S_ISREG(info.st_mode)
                and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077
                and info.st_size==proof['compressed_bytes'])
            with compressed.open('rb') as stream:
                require(hashlib.file_digest(stream,'sha256').hexdigest()==proof['archive_sha256'])
            argv,files=install.configuration(before,namespace)
            for file in active_sources(files):argv+=['-f',str(file)]
            resolved=json.loads(install.command([*argv,'config','--format','json'],env=install.environment()).stdout)
            require(resolved['services']['execution-broker']['image']==image)
            target=resolved['services']['execution-broker']['environment'];original=env(before)
            require(all(target.get(k)=='1' for k in FLAGS)
                and all(k in FLAGS or original.get(k)==v for k,v in target.items()))
            install.save(archive/'before.json',before);install.archive_controller_logs(before,archive)
            others=[json.loads(line) for line in install.command(['docker','ps','-a','--no-trunc','--format','json']).stdout.splitlines() if line]
            install.save(archive/'others.json',[dict(id=c['ID'],name=c['Names'],state=c['State']) for c in others if c['ID']!=current])
            state=dict(identity=identity,stage='prepared',previous_id=current,argv=argv,deadline=time.time()+600)
            install.save(statefile,state)
        if state['stage']=='prepared':
            require(preflight(namespace,image,payload,maintenance_operation=barrier)==before['Id'])
            state['stage']='recreate_intent';install.save(statefile,state)
            try:install.command([*state['argv'],'up','-d','--no-deps','--pull','never','execution-broker'],env=install.environment())
            except subprocess.SubprocessError:pass
        after=install.inspect(namespace+'-execution-broker-1')
        if after['Id']==before['Id'] or not after['State']['Running']:
            if time.time()>=state['deadline']:
                receipt=dict(stage='technical_blocked',owner='devops',next_action='inspect original Compose effect; no repeated up or automatic rollback',
                    operation=operation,delivery_approval=False,model_calls=0)
                state.update(stage='technical_blocked',receipt=receipt);install.save(statefile,state);return receipt
            raise Pending('observe original activation Compose effect; never repeat up')
        verify(before,after);maintenance,_=require_idle(namespace)
        require(maintenance['operation_id']==barrier);Service().stopped(namespace)
        about=Authority(namespace,image).about()
        require(about['v2_enabled'] is True and about['implementation_enabled'] is True and about['maintenance'] is True)
        for row in json.loads(read(archive/'others.json')):
            observed=install.inspect(row['id']);require(observed['Name']=='/'+row['name'] and observed['State']['Status']==row['state'])
        receipt=dict(stage='activated_sealed',namespace=namespace,image=image,container_id=after['Id'],
            issue_id=payload['plan']['issue_id'],exclusive_enabled=True,maintenance_released=False,
            model_calls=0,delivery_approval=False,other_containers_unchanged=True,data_mounts_preserved=True)
        state.update(stage='activated_sealed',receipt=receipt);install.save(statefile,state);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','payload','pin','operation','install-operation'):p.add_argument('--'+key,required=True)
    p.add_argument('--maintenance-operation',help='Current sealed barrier; preserves the original enrollment maintenance identity')
    a=p.parse_args();print(json.dumps(activate(a.namespace,a.image,a.payload,a.pin,a.operation,a.install_operation,maintenance_operation=a.maintenance_operation),sort_keys=True))
