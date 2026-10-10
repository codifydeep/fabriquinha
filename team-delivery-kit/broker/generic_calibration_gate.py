"""Controller primitives for independent generic calibration and durable jobs.

Not a worker API. ``qualify`` consumes controller-authenticated native task/read
records and prior-method inventories from immutable input probes. Calling it
with caller-supplied identities is not authorization. Installed adapters must
fetch those facts themselves before store/run; no agent-facing handler exists.
"""
import hashlib
import json
import re
import time
import os
from types import SimpleNamespace

from docker_grouping import labels
from generic_harness_calibration import digest,validate_policy,validate_receipt


def require(condition):
    if not condition:raise ValueError('exact independent generic calibration binding required')


def required_paths(policy,context):
    return sorted({'/evidence/policy/policy.json',
        *('/evidence/candidate/'+p for p in policy['test_sha256']),
        *('/evidence/candidate/'+m['product_path'] for m in policy['modules']),
        *('/evidence/previous/'+p for p in policy['previous_methods']),
        *('/evidence/controls/'+p for p in context['control_files'])})


def qualify(policy,context,proposal,review,proposal_reads,review_reads):
    sha=digest(policy);validate_policy(policy,sha)
    require(isinstance(context,dict) and set(context)=={'issue_id','author_task','author','cto','reviewer',
        'proposal_wakeup','review_wakeup','previous_methods','execution_sha256','plan_sha256','source_task',
        'criteria','control_files','candidate_volume','controls_volume','policy_volume'})
    require(all(policy[k]==context[k] for k in ('source_task','execution_sha256','plan_sha256','criteria','previous_methods')))
    require(len({context['author'],context['cto'],context['reviewer']})==3)
    controls={m['positive_fixture'] for m in policy['modules']}|{n['fixture'] for n in policy['negatives']}
    require(set(context['control_files'])==controls and len(context['control_files'])==len(controls))
    require(proposal['id']!=review['id'] and context['author_task'] not in (proposal['id'],review['id']))
    artifacts={}
    for task,actor,wakeup,action,reads in (
            (proposal,context['cto'],context['proposal_wakeup'],'propose_calibration',proposal_reads),
            (review,context['reviewer'],context['review_wakeup'],'approve_calibration',review_reads)):
        require(task.get('status')=='completed' and task.get('agent_id')==actor
            and task.get('issue_id')==context['issue_id'] and task.get('wakeup_id')==wakeup)
        raw=(task.get('result') or {}).get('output')
        require(isinstance(raw,str) and 1<=len(raw)<=4096)
        body=json.loads(raw)
        require(isinstance(body,dict) and body.get('execution_authorized') is False
            and body.get('delivery_approval') is False and body==dict(action=action,policy_sha256=sha,
            controls_manifest_sha256=policy['controls_manifest_sha256'],
            execution_authorized=False,delivery_approval=False))
        for path in required_paths(policy,context):
            observed=reads.get(path,{})
            require(type(observed.get('lines')) is int and observed['lines']>0
                and observed['lines']==observed.get('total_lines'))
        artifacts[action]=dict(task_id=task['id'],actor=actor,wakeup_id=wakeup,
            artifact_sha256=digest(body),read_evidence={p:reads[p] for p in required_paths(policy,context)})
    return dict(operation='generic_calibration_registration_v1',policy=policy,policy_sha256=sha,
        context=context,approvals=artifacts,execution_authorized=False,delivery_approval=False)


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_policies('
        'issue_id TEXT,author_task TEXT,record TEXT,PRIMARY KEY(issue_id,author_task))')
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_jobs('
        'job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')


def store(con,record):
    """Only after actual native/probe facts passed qualify; immutable per author."""
    initialize(con);context=record['context']
    require(record.get('operation')=='generic_calibration_registration_v1'
        and record.get('execution_authorized') is False and record.get('delivery_approval') is False
        and record['policy_sha256']==digest(record['policy']))
    validate_policy(record['policy'],record['policy_sha256'])
    key=(context['issue_id'],context['author_task'])
    row=con.execute('SELECT record FROM generic_calibration_policies WHERE issue_id=? AND author_task=?',key).fetchone()
    if row:
        require(json.loads(row[0])==record);return record
    con.execute('INSERT INTO generic_calibration_policies VALUES(?,?,?)',(*key,json.dumps(record,sort_keys=True)))
    return record


def payload(b,record):
    p=record['policy'];context=record['context'];validate_policy(p,record['policy_sha256'])
    image=getattr(b,'GENERIC_CALIBRATION_IMAGE',None) or os.environ.get('BROKER_GENERIC_CALIBRATION_IMAGE')
    require(isinstance(image,str) and bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    for key in ('candidate_volume','controls_volume','policy_volume'):
        require(isinstance(context[key],str) and context[key].startswith(b.PREFIX+'-')
            and bool(re.fullmatch('[A-Za-z0-9_.-]{1,200}',context[key])))
    require(len({context[k] for k in ('candidate_volume','controls_volume','policy_volume')})==3)
    return dict(Image=image,User='10000:10000',Entrypoint=['python'],
        Cmd=['/generic_harness_calibration.py','/candidate','/controls','/policy/policy.json',record['policy_sha256']],
        NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1'],
        Labels={**labels('generic-calibration',b.PREFIX),'delivery-kit.owner':b.OWNER,
            'delivery-kit.calibration-policy':record['policy_sha256'],
            'delivery-kit.calibration-author-task':context['author_task']},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges'],Memory=536870912,NanoCpus=1000000000,PidsLimit=96,
            Mounts=[dict(Type='volume',Source=context[key],Target=target,ReadOnly=True) for key,target in (
                ('candidate_volume','/candidate'),('controls_volume','/controls'),('policy_volume','/policy'))],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'}))


def verify_payload(b,record,value):
    require(value==payload(b,record))


def validate_volumes(b,record):
    context=record['context']
    for role in ('candidate','controls','policy'):
        info=b.docker('GET','/volumes/'+context[role+'_volume']) or {}
        tags=info.get('Labels',{})
        require(tags.get('delivery-kit.owner')==b.OWNER)
        if role=='candidate':require(tags.get('delivery-kit.test-first-task')==context['author_task'])
        else:require(tags.get('delivery-kit.calibration-policy')==record['policy_sha256']
            and tags.get('delivery-kit.calibration-role')==role)


def run(b,con,record,*,now=None):
    """One job; persist each intent before Docker. Unknown effects only observe."""
    initialize(con);context=record['context'];sha=record['policy_sha256']
    registered=con.execute('SELECT record FROM generic_calibration_policies WHERE issue_id=? AND author_task=?',
        (context['issue_id'],context['author_task'])).fetchone()
    require(registered and json.loads(registered[0])==record)
    validate_volumes(b,record)
    expected=payload(b,record)
    try:import harness_qualification,test_first_job
    except ImportError:from broker import harness_qualification,test_first_job
    expected['Env']=harness_qualification.image_environment(SimpleNamespace(IMAGE=expected['Image'],docker=b.docker))
    key=context['issue_id']+':'+context['author_task'];name=b.PREFIX+'-generic-calibration-'+sha[:24]
    identity=dict(name=name,payload=expected,record_sha256=digest(record))
    row=con.execute('SELECT identity,state FROM generic_calibration_jobs WHERE job_key=?',(key,)).fetchone()
    now=time.time() if now is None else now
    if row:
        require(json.loads(row[0])==identity);state=json.loads(row[1])
        if state['stage']=='complete':
            validate_receipt(state['result']['receipt'],record['policy'],sha);return state['result']
        require(state['stage']!='blocked')
    else:
        require(b.docker('GET','/containers/'+name+'/json') is None)
        state=dict(stage='prepared',deadline=now+600,delivery_approval=False)
        con.execute('INSERT INTO generic_calibration_jobs VALUES(?,?,?)',
            (key,json.dumps(identity,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit()
    def save(**changes):
        state.update(changes);con.execute('UPDATE generic_calibration_jobs SET state=? WHERE job_key=?',
            (json.dumps(state,sort_keys=True),key));con.commit()
    if now>=state['deadline']:
        save(stage='blocked',category='calibration_observation_deadline')
        raise ValueError('calibration deadline; preserve existing job for diagnosis')
    if state['stage']=='prepared':
        save(stage='create_intent')
        try:b.docker('POST','/containers/create?name='+name,expected)
        except TimeoutError:raise TimeoutError('observe exact calibration create; never repeat POST') from None
    info=b.docker('GET','/containers/'+name+'/json')
    if info is None:raise TimeoutError('observe exact calibration handle; never recreate')
    test_first_job.verify(b,info,expected)
    if state['stage']=='create_intent':save(stage='created',container_id=info['Id'])
    require(info['Id']==state['container_id'])
    if state['stage']=='created':
        require(info['State']['Status']=='created');save(stage='start_intent')
        try:b.docker('POST','/containers/'+info['Id']+'/start')
        except TimeoutError:raise TimeoutError('observe exact calibration start; never repeat POST') from None
        info=b.docker('GET','/containers/'+info['Id']+'/json')
        if info is None:raise TimeoutError('observe recorded calibration start')
        test_first_job.verify(b,info,expected)
    if info['State']['Status']!='exited':raise TimeoutError('calibration pending; observe same handle')
    raw=b.docker_stdout(info['Id'],include_stderr=info['State']['ExitCode']!=0,limit=65536)
    output_sha256=hashlib.sha256(raw.encode()).hexdigest()
    try:
        require(info['State']['ExitCode']==0)
        receipt=validate_receipt(json.loads(raw),record['policy'],sha)
    except (ValueError,KeyError,TypeError):
        save(stage='blocked',category='executed_calibration_rejected',output_sha256=output_sha256,
            exit_code=info['State']['ExitCode'])
        raise ValueError('actual calibration rejected; no identical retry') from None
    result=dict(container_id=info['Id'],output_sha256=output_sha256,receipt=receipt,delivery_approval=False)
    save(stage='complete',result=result)
    return result


def require_result(b,con,record,red):
    """Observe the original approved job receipt only; never execute a new job."""
    initialize(con);context=record['context'];p=record['policy'];sha=record['policy_sha256']
    require(red['task_id']==context['author_task'] and red['volume']==context['candidate_volume']
        and red['red']['manifest_sha256']==p['candidate_manifest_sha256']
        and red['red']['test_sha256']==p['test_sha256'])
    row=con.execute('SELECT identity,state FROM generic_calibration_jobs WHERE job_key=?',
        (context['issue_id']+':'+context['author_task'],)).fetchone()
    require(row is not None);identity,state=map(json.loads,row)
    expected=payload(b,record)
    try:import harness_qualification
    except ImportError:from broker import harness_qualification
    expected['Env']=harness_qualification.image_environment(SimpleNamespace(IMAGE=expected['Image'],docker=b.docker))
    require(identity==dict(name=b.PREFIX+'-generic-calibration-'+sha[:24],payload=expected,record_sha256=digest(record))
        and state.get('stage')=='complete' and state['result'].get('delivery_approval') is False)
    validate_volumes(b,record)
    return validate_receipt(state['result']['receipt'],p,sha)
