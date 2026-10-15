"""One durable fixed transport experiment; no supplied command, files or network."""
import hashlib
import json
import os
import re
import time
from docker_grouping import grouped_create
from generic_harness_calibration import digest,require
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def validate(proof,sources):
    require(set(proof)=={'operation','passed','sources','checks','model_calls','product_tests_executed',
        'historical_cause_proven','author_retry_authorized','execution_authorized','delivery_approval'})
    require(proof['operation']=='fixed_calibration_transport_probe_v1' and proof['passed'] is True
        and proof['sources']==sources and type(proof['model_calls']) is int and proof['model_calls']==0
        and set(proof['checks'])=={'empty_terminal_accepted','extra_terminal_rejected','duplicate_terminal_rejected',
            'ledger_idempotent','legacy_receipt_preserved'} and all(v is True for v in proof['checks'].values())
        and all(proof[k] is False for k in ('product_tests_executed','historical_cause_proven',
            'author_retry_authorized','execution_authorized','delivery_approval')))


def payload(b,key):
    image=getattr(b,'CALIBRATION_TRANSPORT_PROBE_IMAGE',None) or os.environ.get('BROKER_CALIBRATION_TRANSPORT_PROBE_IMAGE')
    require(isinstance(image,str) and bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    name=b.PREFIX+'-calibration-incident-'+key[:24]
    value=dict(Image=image,User='10000:10000',Entrypoint=['python'],
        Cmd=['-c','import signal,runpy;signal.alarm(90);runpy.run_path("/calibration_transport_probe.py",run_name="__main__")'],
        Env=gate.environment(b,image),Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.calibration-incident':key},
        HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=64,Mounts=[],Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'}))
    return name,grouped_create('POST','/containers/create?name='+name,value,b.PREFIX)


def verify_job(b,info,expected):
    # The Engine serializes an unrequested, empty HostConfig.Mounts as null.
    # This adapter applies only to the volume-free synthetic experiment. The
    # common verifier still rejects real mounts, binds, devices and privileges.
    require(expected['HostConfig']['Mounts']==[])
    if info.get('HostConfig',{}).get('Mounts') is None:
        info={**info,'HostConfig':{**info['HostConfig'],'Mounts':[]}}
    gate.verify_job(b,info,expected)


def run(b,con,key,sources,*,now=None):
    require(isinstance(key,str) and bool(re.fullmatch('[a-f0-9]{64}',key)))
    now=time.time() if now is None else now;name,expected=payload(b,key)
    identity=dict(name=name,payload=expected,sources=sources)
    con.execute('CREATE TABLE IF NOT EXISTS calibration_incident_jobs(incident_id TEXT PRIMARY KEY,identity TEXT,state TEXT)')
    row=con.execute('SELECT identity,state FROM calibration_incident_jobs WHERE incident_id=?',(key,)).fetchone()
    if row:
        require(json.loads(row[0])==identity);state=json.loads(row[1])
        if state['stage']=='complete':
            result=state['result'];require(hashlib.sha256(result['output'].encode()).hexdigest()==result['output_sha256'])
            validate(json.loads(result['output']),sources);return result
        require(state['stage']!='blocked')
    else:
        require(b.docker('GET','/containers/'+name+'/json') is None)
        state=dict(stage='prepared',deadline=now+600)
        con.execute('INSERT INTO calibration_incident_jobs VALUES(?,?,?)',(key,json.dumps(identity,sort_keys=True),json.dumps(state)));con.commit()
    def save(**changes):
        state.update(changes);con.execute('UPDATE calibration_incident_jobs SET state=? WHERE incident_id=?',
            (json.dumps(state,sort_keys=True),key));con.commit()
    if state['stage']=='prepared':
        if now>=state['deadline']:
            save(stage='blocked',category='incident_probe_deadline');raise ValueError('retain expired incident intent')
        save(stage='create_intent')
        try:b.docker('POST','/containers/create?name='+name,expected)
        except TimeoutError:raise TimeoutError('observe exact incident create') from None
    info=b.docker('GET','/containers/'+name+'/json')
    if info is None:raise TimeoutError('observe exact incident job; never recreate')
    verify_job(b,info,expected)
    if state['stage']=='create_intent':save(stage='created',container_id=info['Id'])
    require(state['container_id']==info['Id'])
    if now>=state['deadline'] and info['State']['Status']!='exited':
        save(stage='blocked',category='incident_probe_deadline');raise ValueError('retain stalled incident job')
    if state['stage']=='created':
        require(info['State']['Status']=='created');save(stage='start_intent')
        try:b.docker('POST','/containers/'+info['Id']+'/start')
        except TimeoutError:raise TimeoutError('observe exact incident start') from None
        raise TimeoutError('observe same incident probe')
    if info['State']['Status']!='exited':
        if now>=state['deadline']:
            save(stage='blocked',category='incident_probe_deadline');raise ValueError('retain stalled incident job')
        raise TimeoutError('observe same incident probe')
    raw=b.docker_stdout(info['Id'],include_stderr=info['State']['ExitCode']!=0,limit=16384)
    try:
        require(type(info['State']['ExitCode']) is int and info['State']['ExitCode']==0);validate(json.loads(raw),sources)
    except (ValueError,KeyError,TypeError):
        save(stage='blocked',category='incident_probe_rejected',output_sha256=hashlib.sha256(raw.encode()).hexdigest(),output=raw)
        raise ValueError('fixed incident evidence rejected; no repeat') from None
    result=dict(output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest(),container_id=info['Id'],image=expected['Image'])
    save(stage='complete',result=result);return result
