"""Lease-bound, bounded candidate diagnostics. No dispatch or approval authority.

Only controller code may issue a capability with an authenticated configuration.
Workers may supply the current file hash, never a path, image, argv or source.
Installing this module alone does not enroll or restart an author execution.
"""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import tarfile
import time
import urllib.parse
import uuid
from generic_harness_calibration import require,relative,digest
from literal_inspection_assessment import assess
from literal_author_feedback import FALSE_FLAGS
try:import validation_job,native,native_scope_note
except ImportError:from broker import validation_job,native,native_scope_note


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS author_feedback_capabilities('
        'request_id TEXT PRIMARY KEY,digest TEXT UNIQUE,config TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS author_feedback_jobs('
        'request_id TEXT,candidate_sha256 TEXT,status TEXT,receipt TEXT,PRIMARY KEY(request_id,candidate_sha256))')


def configuration(b,cfg):
    require(set(cfg)=={'task_id','author','issue_id','wakeup_id','source_task','note_sha256','previous_volume',
        'previous_manifest_sha256','test_path','image','worker_image','feedback_sha256','max_candidates','expected'})
    for key in ('task_id','author','issue_id','wakeup_id','source_task'):require(str(uuid.UUID(cfg[key]))==cfg[key])
    for key in ('note_sha256','previous_manifest_sha256','feedback_sha256'):require(bool(re.fullmatch('[a-f0-9]{64}',cfg[key])))
    require(all(bool(re.fullmatch('sha256:[a-f0-9]{64}',cfg[k])) for k in ('image','worker_image')) and type(cfg['max_candidates']) is int
        and cfg['max_candidates']==4 and cfg['previous_volume'].startswith(b.PREFIX+'-')
        and bool(re.fullmatch('[a-zA-Z0-9_.-]{1,200}',cfg['previous_volume'])))
    for key,environment in (('image','BROKER_LITERAL_AUTHOR_FEEDBACK_IMAGE'),('worker_image','BROKER_AUTHOR_FEEDBACK_WORKER_IMAGE')):
        if os.environ.get(environment):require(cfg[key]==os.environ[environment])
    relative(cfg['test_path']);require(cfg['test_path'].endswith('.py'))
    expected=cfg['expected'];require(set(expected)=={'initial_expected','poll_minimum','stale_expected'}
        and all(type(expected[k]) is int and 0<=expected[k]<=100 for k in ('initial_expected','poll_minimum'))
        and isinstance(expected['stale_expected'],str) and 1<=len(expected['stale_expected'])<=256)


def binding(b,con,request,cfg):
    configuration(b,cfg)
    row=con.execute('SELECT g.mode,g.used,g.attempt,g.task_id,g.deadline AS grant_deadline,'
        'n.task_id AS native_task_id,n.agent_id,n.issue_id,n.scope,l.status,l.name,l.deadline AS lease_deadline '
        'FROM grants g JOIN native_bindings n USING(request_id) JOIN leases l USING(request_id) '
        'WHERE g.request_id=?',(request,)).fetchone()
    require(row and row['mode']=='implementation' and row['used']==1 and row['status']=='running'
        and min(row['grant_deadline'],row['lease_deadline'])>time.time()
        and row['task_id']==row['native_task_id']==cfg['task_id'] and row['agent_id']==cfg['author']
        and row['issue_id']==cfg['issue_id'] and row['scope'].split(':')[-2:]==['implementation',cfg['task_id']]
        and row['name']==b.PREFIX+'-job-'+request
        and row['attempt']==con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(cfg['task_id'],)).fetchone()[0])
    return dict(row,request_id=request)


def native_running(b,row,cfg):
    settings=json.loads((b.STATE/'native.json').read_text())
    require(settings['agents'].get(cfg['author'])=='implementation')
    task=native.task_record(settings,cfg['task_id'],cfg['author'])
    require(task.get('status')=='running' and task.get('agent_id')==cfg['author']
        and task.get('issue_id')==cfg['issue_id'] and task.get('wakeup_id')==cfg['wakeup_id']
        and hashlib.sha256(native_scope_note.canonical(task.get('handoff_note',''),cfg['wakeup_id']).encode()).hexdigest()==cfg['note_sha256'])


def issue(b,request,cfg):
    with b.LOCK,b.db() as con:
        initialize(con);row=binding(b,con,request,cfg);native_running(b,row,cfg)
        old=con.execute('SELECT config FROM author_feedback_capabilities WHERE request_id=?',(request,)).fetchone()
        require(not old or json.loads(old[0])==cfg)
        token=hmac.new(b.TOKEN.encode(),('literal-author-feedback-v1:'+request+':'+digest(cfg)).encode(),hashlib.sha256).hexdigest()
        con.execute('INSERT OR IGNORE INTO author_feedback_capabilities VALUES(?,?,?)',
            (request,hashlib.sha256(token.encode()).hexdigest(),json.dumps(cfg,sort_keys=True)))
        return token


def attached_config(b,request):
    """Expose only an already issued controller capability, never auto-enroll."""
    with b.db() as con:
        initialize(con);row=con.execute('SELECT config FROM author_feedback_capabilities WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    cfg=json.loads(row[0])
    info=b.docker('GET','/containers/'+b.PREFIX+'-job-'+request+'/json') or {}
    require(info.get('Image')==cfg['worker_image'])
    token=issue(b,request,cfg)
    return dict(request_id=request,task_id=cfg['task_id'],capability=token,
        **{k:cfg[k] for k in ('test_path','previous_manifest_sha256','feedback_sha256','expected')})


def archive_file(raw,basename):
    require(isinstance(raw,bytes) and 0<len(raw)<=65536)
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as stream:
        files=stream.getmembers();require(len(files)==1)
        member=files[0];require(member.isreg() and member.name==basename and 0<member.size<=32768)
        file=stream.extractfile(member);require(file is not None)
        value=file.read(32769);require(len(value)==member.size);return value


def workspace(b,row):return b.PREFIX+'-work-'+hashlib.sha256(row['scope'].encode()).hexdigest()[:32]


def current_bytes(b,row,cfg):
    info=b.docker('GET','/containers/'+row['name']+'/json') or {}
    labels=info.get('Config',{}).get('Labels',{});mounts=info.get('HostConfig',{}).get('Mounts',[])
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get('delivery-kit.request')==row['request_id']
        and info.get('State',{}).get('Running') is True and info.get('Image')==cfg['worker_image'])
    own=workspace(b,row)
    require(any(m.get('Type')=='volume' and m.get('Source')==own and m.get('Target')=='/workspace'
        and m.get('ReadOnly',False) is False for m in mounts))
    volume=(b.docker('GET','/volumes/'+own) or {}).get('Labels',{})
    require(volume.get('delivery-kit.owner')==b.OWNER and volume.get('delivery-kit.scope')==row['scope'])
    previous=(b.docker('GET','/volumes/'+cfg['previous_volume']) or {}).get('Labels',{})
    require(previous.get('delivery-kit.owner')==b.OWNER and cfg['source_task'] in
        (previous.get('delivery-kit.test-first-task'),previous.get('delivery-kit.source-task')))
    connection=b.DockerConnection('localhost',timeout=10)
    try:
        connection.request('GET','/v1.45/containers/'+row['name']+'/archive?path='+
            urllib.parse.quote('/workspace/'+cfg['test_path'],safe='/'))
        response=connection.getresponse();require(response.status==200)
        return archive_file(response.read(65537),PurePosixPath(cfg['test_path']).name)
    finally:connection.close()


def payload(b,row,cfg,sha):
    return dict(Image=cfg['image'],User='10000:10000',Entrypoint=['python'],
        Cmd=['/literal_author_feedback.py','/previous','/candidate',cfg['previous_manifest_sha256'],cfg['test_path'],sha],
        Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'],Labels={'delivery-kit.author-feedback':row['request_id'],
            'delivery-kit.author-feedback-contract':digest(cfg),'delivery-kit.candidate-sha256':sha},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=536870912,NanoCpus=1000000000,PidsLimit=64,Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},
            Mounts=[dict(Type='volume',Source=cfg['previous_volume'],Target='/previous',ReadOnly=True),
                dict(Type='volume',Source=workspace(b,row),Target='/candidate',ReadOnly=True)]))


def validate_feedback(value,cfg,sha):
    require(value['operation']=='literal_author_feedback_v1' and value['candidate_sha256']==sha
        and value['feedback_sha256']==cfg['feedback_sha256'] and value['previous_manifest_sha256']==cfg['previous_manifest_sha256']
        and value['test_path']==cfg['test_path'] and value['expected']==cfg['expected']
        and value['outside_literal_bytes_preserved'] is True and value['candidate_bytes_stable_during_measurement'] is True
        and value['non_target_verification']=='not_performed_in_feedback' and value['evidence_scope']=='current_file_fixed_diagnostic_only'
        and type(value['model_calls']) is int and value['model_calls']==0 and all(value[k] is False for k in FALSE_FLAGS))
    capture=value['capture'];require(set(capture)=={'field','literal','literal_line','assignment'}
        and capture['field']=='poll_requests' and capture['literal']=='NODE_HARNESS'
        and type(capture['literal_line']) is int and 0<capture['literal_line']<=32768
        and capture['assignment']=='snap.poll_requests = latestCount();')
    reports=value['reports'];require(all(len(r['stale_guard_text'])<=256 for r in reports.values()))
    assessment=assess({'counterexample':{'facts':{'assertion_bindings':cfg['expected']}}},
        dict(reports=reports,stale_witness_selectivity_passed=value['checks_passed']))
    require(value['failed_fields']==[field for field,key in (('initial_requests','initial_requests_passed'),
        ('poll_requests','poll_requests_passed'),('stale_guard_text','stale_ordering_passed')) if not assessment[key]])


def execute(b,token,body):
    require(isinstance(body,dict) and set(body)=={'candidate_sha256'} and isinstance(body['candidate_sha256'],str)
        and bool(re.fullmatch('[a-f0-9]{64}',body['candidate_sha256'])) and isinstance(token,str)
        and bool(re.fullmatch('[a-f0-9]{64}',token)))
    sha=body['candidate_sha256']
    with b.LOCK,b.db() as con:
        initialize(con);cap=con.execute('SELECT * FROM author_feedback_capabilities WHERE digest=?',
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone();require(cap)
        cfg=json.loads(cap['config']);request=cap['request_id'];row=binding(b,con,request,cfg);native_running(b,row,cfg)
        require(hashlib.sha256(current_bytes(b,row,cfg)).hexdigest()==sha)
        old=con.execute('SELECT status,receipt FROM author_feedback_jobs WHERE request_id=? AND candidate_sha256=?',(request,sha)).fetchone()
        if old:
            require(old['status'] in ('observing','complete'))
            if old['status']=='complete':
                receipt=json.loads(old['receipt']);validate_feedback(receipt,cfg,sha)
                row=binding(b,con,request,cfg);native_running(b,row,cfg);return receipt
        else:
            require(con.execute('SELECT count(*) FROM author_feedback_jobs WHERE request_id=?',(request,)).fetchone()[0]<cfg['max_candidates'])
            con.execute('INSERT INTO author_feedback_jobs VALUES(?,?,?,?)',(request,sha,'observing','{}'));con.commit()
        try:
            job=validation_job.run(b,cfg['task_id'],'structure',payload(b,row,cfg,sha))
            require(job['exit_code']==0 and job['approval'] is False
                and job['output_sha256']==hashlib.sha256(job['output'].encode()).hexdigest() and len(job['output'].encode())<=16384)
            value=json.loads(job['output']);validate_feedback(value,cfg,sha)
            row=binding(b,con,request,cfg);native_running(b,row,cfg)
            require(hashlib.sha256(current_bytes(b,row,cfg)).hexdigest()==sha)
            receipt={**value,'request_id':request,'task_id':cfg['task_id'],
                'validation_job_key':job['validation_job_key'],'validation_contract_sha256':job['validation_contract_sha256']}
            con.execute("UPDATE author_feedback_jobs SET status='complete',receipt=? WHERE request_id=? AND candidate_sha256=?",
                (json.dumps(receipt,sort_keys=True),request,sha));return receipt
        except validation_job.Pending:
            return dict(operation='literal_author_feedback_pending_v1',candidate_sha256=sha,
                next_action='observe_same_feedback_job',**{k:False for k in FALSE_FLAGS})
        except Exception as error:
            con.execute("UPDATE author_feedback_jobs SET status='failed',receipt=? WHERE request_id=? AND candidate_sha256=?",
                (json.dumps(dict(category=type(error).__name__,delivery_approval=False)),request,sha));con.commit();raise
