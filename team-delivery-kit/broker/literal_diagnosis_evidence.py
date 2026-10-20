"""Controller-owned lineage bundle and one proven read-contract recovery.

No worker endpoint. Existing failed tasks and independent rejections remain
immutable. The repair grants a fresh readonly diagnostic, not author capacity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from generic_harness_calibration import digest,require
import literal_diagnosis_bundle as helper
try:
    import validation_job,controller_maintenance as maintenance,native_scope_note
except ImportError:
    from broker import validation_job,controller_maintenance as maintenance,native_scope_note


def identity(cfg,s):
    require(cfg.get('feedback_strategy') and len(s['history'])==1 and s['revision']==0)
    image=os.environ.get('BROKER_LITERAL_DIAGNOSIS_BUNDLE_IMAGE','');require(re.fullmatch('sha256:[a-f0-9]{64}',image))
    p=cfg['feedback_strategy']['policy']
    return dict(config_sha256=digest(cfg),history_sha256=digest(s['history']),image=image,
        helper_sha256=hashlib.sha256(Path(helper.__file__).read_bytes()).hexdigest(),test_path=cfg['test_path'],
        sources=dict(original=dict(volume=cfg['source']['candidate_volume'],manifest=cfg['source']['prepared']['manifest_sha256']),
            seed=dict(volume=p['previous_volume'],manifest=p['previous_manifest_sha256']),
            candidate=dict(volume=s['snapshot']['volume'],manifest=s['inspection']['candidate_manifest_sha256'])))


def payload(ident,name,labels,mode='create'):
    require(mode in ('create','verify'));sources=ident['sources']
    return dict(Image=ident['image'],User='10000:10000',Entrypoint=['python'],
        Cmd=['/literal_diagnosis_bundle.py','/original','/seed','/candidate','/bundle',
            *[sources[n]['manifest'] for n in ('original','seed','candidate')],ident['test_path'],mode],
        Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],Labels=labels,
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=32,
            Mounts=[dict(Type='volume',Source=v['volume'],Target='/'+n,ReadOnly=True) for n,v in sources.items()]+
                [dict(Type='volume',Source=name,Target='/bundle',ReadOnly=mode=='verify')]))


def prepare(b,cfg,s):
    ident=identity(cfg,s);key=digest(ident);name=b.PREFIX+'-diagnosis-evidence-'+key[:24]
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.diagnosis-evidence':key}
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS literal_diagnosis_bundles(bundle_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        row=con.execute('SELECT identity,state FROM literal_diagnosis_bundles WHERE bundle_key=?',(key,)).fetchone()
        if row:require(json.loads(row[0])==ident);state=json.loads(row[1])
        else:
            require(b.docker('GET','/volumes/'+name) is None)
            state=dict(stage='create_intent',name=name)
            con.execute('INSERT INTO literal_diagnosis_bundles VALUES(?,?,?)',(key,json.dumps(ident,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit()
            try:b.docker('POST','/volumes/create',dict(Name=name,Labels=labels))
            except TimeoutError:raise validation_job.Pending('observe same diagnosis evidence volume') from None
    volume=b.docker('GET','/volumes/'+name)
    if volume is None:raise validation_job.Pending('observe diagnosis evidence intent; do not recreate')
    require(all(volume.get('Labels',{}).get(k)==v for k,v in labels.items()))
    job=validation_job.run(b,s['author_task'],'structure',payload(ident,name,labels))
    require(job['exit_code']==0 and job['output_sha256']==hashlib.sha256(job['output'].encode()).hexdigest())
    result=json.loads(job['output']);require(result['operation']=='literal_diagnosis_bundle_v1' and result['source_unchanged'] is True
        and result['source_reset'] is False and result['delivery_approval'] is False and result['model_calls']==0
        and result['report']['source_manifests']=={k:v['manifest'] for k,v in ident['sources'].items()})
    receipt=dict(volume=name,identity_sha256=key,manifest_sha256=result['manifest_sha256'],report=result['report'],validation_job=job)
    if state.get('receipt'):require(state['receipt']==receipt)
    else:
        with b.db() as con:
            con.execute('UPDATE literal_diagnosis_bundles SET state=? WHERE bundle_key=?',
                (json.dumps(dict(state,stage='complete',receipt=receipt),sort_keys=True),key))
    return receipt


def validate(b,cfg,s,receipt):
    require(receipt==prepare(b,cfg,s))


def failed_read_proof(cfg,s,task,reads):
    """Pure guard for the exact third-root contract failure, not any ValueError."""
    try:import literal_maintenance_workflow as flow
    except ImportError:from broker import literal_maintenance_workflow as flow
    require(cfg.get('feedback_strategy') and s['stage']=='blocked' and s['category']=='maintenance_evidence_rejected'
        and s['last_error']['phase']=='diagnose_wait' and s['last_error']['type']=='ValueError'
        and s['cto_escalation']==flow.escalation_binding(cfg,s) and not s.get('diagnosis')
        and task['status']=='completed' and task['agent_id']==cfg['cto'] and task['issue_id']==s['issue_id']
        and task['wakeup_id']==s['wakeup_id'] and len({cfg['cto'],cfg['reviewer'],cfg['author']})==3)
    prefix='DELIVERY_PLANNING_START '+s['marker']+'\nSource: '+flow.dispatch_source(cfg)+'\n'
    note=native_scope_note.canonical(task['handoff_note'],s['wakeup_id']);require(note.startswith(prefix));instruction=note[len(prefix):]
    require(any(s['marker']==digest(dict(config=cfg,phase='diagnose',instruction=n,revision=0)) for n in (instruction,instruction+'\n')))
    expected={'/evidence/'+n+'/'+cfg['test_path'] for n in ('candidate','previous','seed')}
    require(set(re.findall(r'^DELIVERY_REVIEW_READ_PATH:(.+)$',instruction,re.M))==expected
        and set(reads)==expected-{'/evidence/seed/'+cfg['test_path']})
    require(all(type(v.get('lines')) is int and v['lines']>0 and v['lines']==v.get('total_lines') for v in reads.values()))
    require(isinstance((task.get('result') or {}).get('output'),str))
    return dict(task_id=task['id'],wakeup_id=s['wakeup_id'],marker=s['marker'],
        handoff_note_sha256=hashlib.sha256(note.encode()).hexdigest(),
        output_sha256=hashlib.sha256(task['result']['output'].encode()).hexdigest(),read_evidence=reads,
        failure='third_root_not_supported',decision_accepted=False)


def recover(b,key,operation):
    try:import literal_maintenance_workflow as flow,literal_maintenance_effects as lane
    except ImportError:from broker import literal_maintenance_workflow as flow,literal_maintenance_effects as lane
    with b.db() as con:
        seal=maintenance.current(con);require(seal and seal['stage']=='sealed' and seal['operation_id']==operation)
        require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
        cfg,s=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(key,)).fetchone())
        con.execute('CREATE TABLE IF NOT EXISTS literal_diagnosis_read_recoveries(workflow_key TEXT PRIMARY KEY,receipt TEXT)')
        row=con.execute('SELECT receipt FROM literal_diagnosis_read_recoveries WHERE workflow_key=?',(key,)).fetchone()
        if row:
            r=json.loads(row[0]);require(r['config_sha256']==digest(cfg) and s.get('diagnosis_read_recovery')==digest(r));return r
    require(not maintenance.native_active(b));fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx);flow.authenticate_rejections(cfg,s,fx)
    matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']];require(len(matches)==1)
    task=fx.plans.task(matches[0]['id'],cfg['cto']);proof=failed_read_proof(cfg,s,task,fx.plans.reads(task));binding=fx.old.binding(task,cfg['cto'])
    with b.db() as con:
        lease=con.execute('SELECT status FROM leases WHERE request_id=?',(binding['request_id'],)).fetchone();require(lease and lease[0]=='closed')
    r=dict(operation='recover_literal_diagnosis_read_contract_v1',workflow_key=key,config_sha256=digest(cfg),
        previous_state=s,failed_task=proof,maintenance_operation=operation,additional_diagnosis_limit=1,
        source_reset=False,author_retry_authorized=False,delivery_approval=False)
    updated=dict(s,stage='diagnosis_bundle',diagnosis_read_recovery=digest(r),phase_started=time.time(),
        required_action='Prepare verified original/seed projection under supported readonly paths before one fresh CTO diagnosis')
    with b.LOCK,b.db() as con:
        con.execute('BEGIN IMMEDIATE');require(maintenance.current(con)==seal)
        require(json.loads(con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(key,)).fetchone()[0])==s)
        con.execute('INSERT INTO literal_diagnosis_read_recoveries VALUES(?,?)',(key,json.dumps(r,sort_keys=True)))
        con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),key))
    return r
