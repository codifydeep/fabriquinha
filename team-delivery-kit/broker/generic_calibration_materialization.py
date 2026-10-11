"""Fixed durable controller job writing only newly owned policy/control volumes.

No worker workspace, credentials, socket or arbitrary command is available.
The result materializes data only: no tests, approvals or delivery are executed.
Unknown volume/container create or start acknowledgments are observed, not
replayed. Inputs come exclusively from the persisted native proposal collector.
"""
import base64
import hashlib
import json
import os
import re
import time
import zlib

from docker_grouping import labels
from generic_harness_calibration import digest
from generic_calibration_bundle_writer import expected_files
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_materializations('
        'issue_id TEXT,author_task TEXT,identity TEXT,state TEXT,PRIMARY KEY(issue_id,author_task))')


def identity(b,record):
    sha=digest(record);expected_files(record,sha)
    image=getattr(b,'GENERIC_CALIBRATION_WRITER_IMAGE',None) or os.environ.get('BROKER_GENERIC_CALIBRATION_WRITER_IMAGE')
    gate.require(isinstance(image,str) and bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    raw=json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    gate.require(len(raw)<=1048576)
    encoded=base64.b64encode(zlib.compress(raw,9)).decode()
    gate.require(len(encoded)<=98304)
    volumes={role:dict(Name=b.PREFIX+'-calibration-'+role+'-'+sha[:24],Labels={
        'delivery-kit.owner':b.OWNER,'delivery-kit.calibration-policy':record['policy_sha256'],
        'delivery-kit.calibration-role':role,'delivery-kit.calibration-bundle':sha}) for role in ('controls','policy')}
    env=writer_environment(b,image)
    payload=dict(Image=image,User='0:0',Entrypoint=['python'],
        Cmd=['/generic_calibration_bundle_writer.py','/controls','/policy','--environment',sha],
        # Current Engine omits legacy Config.NetworkDisabled. Isolation uses
        # mandatory HostConfig.NetworkMode=none, not an invented observation.
        Env=[*env,'CALIBRATION_BUNDLE_ZLIB='+encoded],
        Labels={**labels('calibration-materialization',b.PREFIX),'delivery-kit.owner':b.OWNER,
            'delivery-kit.calibration-bundle':sha,'delivery-kit.calibration-policy':record['policy_sha256']},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=536870912,NanoCpus=1000000000,PidsLimit=96,
            Mounts=[dict(Type='volume',Source=volumes[role]['Name'],Target='/'+role,ReadOnly=False) for role in volumes],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'}))
    return dict(name=b.PREFIX+'-calibration-materialization-'+sha[:24],payload=payload,volumes=volumes,bundle_sha256=sha)


def writer_environment(b,image):
    info=b.docker('GET','/images/'+image+'/json') or {}
    gate.require(info.get('Id')==image and not info.get('Config',{}).get('Volumes'))
    allowed={'PATH':r'[/A-Za-z0-9_.:-]{1,2048}','LANG':r'C\.UTF-?8',
        'GPG_KEY':r'[a-fA-F0-9]{40}','PYTHON_VERSION':r'[0-9]+\.[0-9]+\.[0-9]+',
        'PYTHON_SHA256':r'[a-f0-9]{64}','PYTHONDONTWRITEBYTECODE':r'1','PYTHONUNBUFFERED':r'1'}
    values=info.get('Config',{}).get('Env',[]);environment={}
    gate.require(isinstance(values,list) and len(values)<=16)
    for value in values:
        gate.require(isinstance(value,str) and '=' in value)
        key,text=value.split('=',1)
        gate.require(key in allowed and key not in environment and bool(re.fullmatch(allowed[key],text)))
        environment[key]=text
    environment['PYTHONDONTWRITEBYTECODE']='1'
    return [k+'='+v for k,v in sorted(environment.items())]


def validate_receipt(receipt,record):
    files=expected_files(record,digest(record))
    expected=dict(operation='generic_calibration_bundle_materialized_v1',bundle_sha256=digest(record),
        policy_sha256=record['policy_sha256'],controls_manifest_sha256=record['policy']['controls_manifest_sha256'],
        policy_manifest_sha256=hashlib.sha256(files['policy']['manifest.json'].encode()).hexdigest(),
        tests_executed=False,execution_authorized=False,delivery_approval=False)
    gate.require(isinstance(receipt,dict) and receipt==expected
        and all(receipt[k] is False for k in ('tests_executed','execution_authorized','delivery_approval')))
    return receipt


def verify(b,info,expected):
    try:import test_first_job
    except ImportError:from broker import test_first_job
    test_first_job.verify(b,info,expected)
    host=info['HostConfig']
    gate.require(not any(host.get(k) for k in ('Privileged','Binds','Devices','DeviceRequests','CapAdd')))
    wanted={(m['Source'],m['Target'],not m['ReadOnly']) for m in expected['HostConfig']['Mounts']}
    actual={(m.get('Name'),m.get('Destination'),m.get('RW')) for m in info.get('Mounts',[]) if m.get('Type')=='volume'}
    gate.require(actual==wanted and all(m.get('Type')=='volume' or
        m.get('Type')=='tmpfs' and m.get('Destination') in expected['HostConfig']['Tmpfs'] for m in info.get('Mounts',[])))


def run(b,con,issue,author_task,*,now=None):
    initialize(con)
    exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='generic_calibration_proposals'").fetchone()
    gate.require(exists is not None)
    proposal=con.execute('SELECT record FROM generic_calibration_proposals WHERE issue_id=? AND author_task=?',
        (issue,author_task)).fetchone()
    gate.require(proposal is not None);record=json.loads(proposal[0]);wanted=identity(b,record)
    row=con.execute('SELECT identity,state FROM generic_calibration_materializations WHERE issue_id=? AND author_task=?',
        (issue,author_task)).fetchone()
    now=time.time() if now is None else now
    if row:
        gate.require(json.loads(row[0])==wanted);s=json.loads(row[1])
        gate.require(s['stage']!='blocked')
        if s['stage']=='complete':
            validate_receipt(s['result']['receipt'],record)
            return s['result']
    else:
        # Colliding preexisting resources cannot silently become this job's
        # inputs, even if their labels happen to look familiar.
        gate.require(b.docker('GET','/containers/'+wanted['name']+'/json') is None)
        for value in wanted['volumes'].values():gate.require(b.docker('GET','/volumes/'+value['Name']) is None)
        s=dict(stage='prepare_volumes',deadline=now+600,volumes={role:'prepared' for role in wanted['volumes']},
            execution_authorized=False,delivery_approval=False)
        con.execute('INSERT INTO generic_calibration_materializations VALUES(?,?,?,?)',
            (issue,author_task,json.dumps(wanted,sort_keys=True),json.dumps(s,sort_keys=True)));con.commit()
    def save(**changes):
        s.update(changes)
        con.execute('UPDATE generic_calibration_materializations SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),issue,author_task));con.commit()
    if now>=s['deadline']:
        save(stage='blocked',category='materialization_observation_deadline')
        raise ValueError('materialization deadline; preserve exact resources for diagnosis')
    for role,value in wanted['volumes'].items():
        if s['volumes'][role]=='prepared':
            s['volumes'][role]='create_intent';save()
            try:b.docker('POST','/volumes/create',value)
            except TimeoutError:raise TimeoutError('observe exact materialization volume; never repeat POST') from None
        info=b.docker('GET','/volumes/'+value['Name'])
        if info is None:raise TimeoutError('observe recorded volume creation; never recreate')
        gate.require(info.get('Name')==value['Name'] and info.get('Labels')==value['Labels'])
        if s['volumes'][role]=='create_intent':s['volumes'][role]='created';save()
    if s['stage']=='prepare_volumes':save(stage='prepared')
    if s['stage']=='prepared':
        save(stage='create_intent')
        try:b.docker('POST','/containers/create?name='+wanted['name'],wanted['payload'])
        except TimeoutError:raise TimeoutError('observe exact materialization create; never repeat POST') from None
    info=b.docker('GET','/containers/'+wanted['name']+'/json')
    if info is None:raise TimeoutError('observe exact materialization handle; never recreate')
    verify(b,info,wanted['payload'])
    if s['stage']=='create_intent':save(stage='created',container_id=info['Id'])
    gate.require(info['Id']==s['container_id'])
    if s['stage']=='created':
        gate.require(info['State']['Status']=='created');save(stage='start_intent')
        try:b.docker('POST','/containers/'+info['Id']+'/start')
        except TimeoutError:raise TimeoutError('observe exact materialization start; never repeat POST') from None
        info=b.docker('GET','/containers/'+info['Id']+'/json')
        if info is None:raise TimeoutError('observe recorded materialization start')
        verify(b,info,wanted['payload']);gate.require(info['Id']==s['container_id'])
    if info['State']['Status']!='exited':raise TimeoutError('materialization pending; observe same handle')
    raw=b.docker_stdout(info['Id'],include_stderr=info['State']['ExitCode']!=0,limit=65536)
    sha=hashlib.sha256(raw.encode()).hexdigest()
    try:
        gate.require(info['State']['ExitCode']==0)
        receipt=validate_receipt(json.loads(raw),record)
    except (ValueError,KeyError,TypeError):
        save(stage='blocked',category='executed_materialization_rejected',output_sha256=sha,exit_code=info['State']['ExitCode'])
        raise ValueError('actual materialization rejected; no identical retry') from None
    result=dict(container_id=info['Id'],output_sha256=sha,receipt=receipt,
        controls_volume=wanted['volumes']['controls']['Name'],policy_volume=wanted['volumes']['policy']['Name'])
    save(stage='complete',result=result)
    return result
