"""Fixed readonly seam probe with durable Docker effects; controller-only."""
import hashlib
import json
import os
import re
import time
from docker_grouping import labels,grouped_create
from generic_harness_calibration import digest,require
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def payload(b,c):
    image=getattr(b,'GENERIC_CALIBRATION_SEAM_IMAGE',None) or os.environ.get('BROKER_GENERIC_CALIBRATION_SEAM_IMAGE')
    require(isinstance(image,str) and bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    volume=c['candidate_volume']
    require(volume.startswith(b.PREFIX+'-') and bool(re.fullmatch('[A-Za-z0-9_.-]{1,200}',volume)))
    return dict(Image=image,User='10000:10000',Entrypoint=['python'],
        Cmd=['/generic_calibration_seam_probe.py','/candidate',c['prepared']['manifest_sha256'],
            json.dumps(c['prepared']['test_sha256'],sort_keys=True,separators=(',',':'))],
        Env=gate.environment(b,image),Labels={**labels('calibration-seam',b.PREFIX),
            'delivery-kit.owner':b.OWNER,'delivery-kit.calibration-seam-author':c['author_task']},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=64,
            Mounts=[dict(Type='volume',Source=volume,Target='/candidate',ReadOnly=True)],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=16m,mode=1777'}))


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_seam_jobs('
        'job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')


def run(b,con,c,*,now=None):
    """Caller authenticates sealed maintenance and frozen source before each call."""
    try:import generic_calibration_capability_recovery as capability
    except ImportError:from broker import generic_calibration_capability_recovery as capability
    initialize(con);now=time.time() if now is None else now
    tags=(b.docker('GET','/volumes/'+c['candidate_volume']) or {}).get('Labels',{})
    require(tags.get('delivery-kit.owner')==b.OWNER and tags.get('delivery-kit.test-first-task')==c['author_task'])
    expected=payload(b,c);key=c['issue_id']+':'+c['author_task']
    identity=dict(name=b.PREFIX+'-calibration-seam-'+digest(c)[:24],payload=expected,config_sha256=digest(c))
    # Preserve the recorded pre-adapter plan, including uncertain creates. The
    # controller boundary deterministically groups every POST; verify exactly
    # that effective payload, not a broader set of acceptable labels.
    effective=grouped_create('POST','/containers/create?name='+identity['name'],expected,b.PREFIX)
    row=con.execute('SELECT identity,state FROM generic_calibration_seam_jobs WHERE job_key=?',(key,)).fetchone()
    if row:
        require(json.loads(row[0])==identity);state=json.loads(row[1])
        if state['stage']=='complete':
            result=state['result'];raw=result['output']
            require(result['approval'] is False and type(result['exit_code']) is int and result['exit_code']==0
                and hashlib.sha256(raw.encode()).hexdigest()==result['output_sha256'])
            capability.seam(json.loads(raw),c);return result
        require(state['stage']!='blocked')
    else:
        require(b.docker('GET','/containers/'+identity['name']+'/json') is None)
        state=dict(stage='prepared',deadline=now+600,delivery_approval=False)
        con.execute('INSERT INTO generic_calibration_seam_jobs VALUES(?,?,?)',
            (key,json.dumps(identity,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit()
    def save(**changes):
        state.update(changes);con.execute('UPDATE generic_calibration_seam_jobs SET state=? WHERE job_key=?',
            (json.dumps(state,sort_keys=True),key));con.commit()
    if now>=state['deadline']:
        save(stage='blocked',category='seam_observation_deadline');raise ValueError('retain exact seam job; no identical retry')
    if state['stage']=='prepared':
        save(stage='create_intent')
        try:b.docker('POST','/containers/create?name='+identity['name'],effective)
        except TimeoutError:raise TimeoutError('observe exact seam create; never repeat POST') from None
    info=b.docker('GET','/containers/'+identity['name']+'/json')
    if info is None:raise TimeoutError('observe exact seam handle; never recreate')
    gate.verify_job(b,info,effective)
    if state['stage']=='create_intent':save(stage='created',container_id=info['Id'])
    require(info['Id']==state['container_id'])
    if state['stage']=='created':
        require(info['State']['Status']=='created');save(stage='start_intent')
        try:b.docker('POST','/containers/'+info['Id']+'/start')
        except TimeoutError:raise TimeoutError('observe exact seam start; never repeat POST') from None
        info=b.docker('GET','/containers/'+info['Id']+'/json')
        if info is None:raise TimeoutError('observe recorded seam start')
        gate.verify_job(b,info,effective);require(info['Id']==state['container_id'])
    if info['State']['Status']!='exited':raise TimeoutError('seam probe pending; observe same handle')
    raw=b.docker_stdout(info['Id'],include_stderr=info['State']['ExitCode']!=0,limit=65536)
    output_sha=hashlib.sha256(raw.encode()).hexdigest()
    try:
        require(type(info['State']['ExitCode']) is int and info['State']['ExitCode']==0)
        capability.seam(json.loads(raw),c)
    except (ValueError,KeyError,TypeError):
        save(stage='blocked',category='seam_actual_probe_rejected',output_sha256=output_sha,output=raw)
        raise ValueError('actual seam rejected; no identical retry') from None
    result=dict(container_id=info['Id'],output=raw,output_sha256=output_sha,exit_code=0,approval=False)
    save(stage='complete',result=result);return result
