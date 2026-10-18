"""Qualified canonical base migration before any literal-maintenance author.

The completed legacy copy and its intent remain untouched. A separate journal
may copy only that fully hash-inspected readonly volume to the canonical name.
This is installation repair, not permission to retry an author or weaken gates.
"""
import hashlib
import json
import os
import re
import time
from generic_harness_calibration import digest,require
from docker_grouping import grouped_create
try:
    import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
    import controller_maintenance as maintenance,validation_job
    from test_first_job import digest as job_digest
except ImportError:
    from broker import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
    from broker import controller_maintenance as maintenance,validation_job
    from broker.test_first_job import digest as job_digest


def copy_identity(b,cfg,old):
    payload=grouped_create('POST','/containers/create?name=validation',lane.copy_payload(cfg,old),b.PREFIX)
    source=cfg['source']['author_task'];key=job_digest(dict(task=source,kind='structure',payload=payload))
    expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':source,'delivery-kit.validation-job':key}}
    return key,dict(task=source,kind='structure',name=b.PREFIX+'-validation-job-'+source+'-'+key[:12],payload=expected)


def completed_copy(con,b,cfg,old):
    key,identity=copy_identity(b,cfg,old)
    row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone();require(row)
    actual,state=map(json.loads,row);require(actual==identity and state['stage']=='complete')
    result=state['result'];require(result['approval'] is False and result['exit_code']==0
        and result['container_id']==state['container_id'] and result['validation_job_key']==key
        and result['validation_contract_sha256']==job_digest(identity)
        and result['output']=='base_copy_complete\n'
        and result['output_sha256']==hashlib.sha256(result['output'].encode()).hexdigest())
    return result


def qualify(b,cfg,state,old,new,spec=None):
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':state['issue_id'],
        'delivery-kit.base-sha':cfg['base']['base_sha']}
    require(state.get('stage')=='blocked' and state.get('category')=='maintenance_evidence_rejected'
        and set(state.get('decisions',{}))=={'triage','plan','permit'}
        and state.get('revision')==0 and not state.get('history') and not state.get('author_task')
        and not state.get('prepared') and not state.get('canonical_base_recovery')
        and state['source_reset'] is False and state['functional_red'] is False and state['delivery_approval'] is False
        and old==dict(identity=dict(name=b.PREFIX+'-literal-base-'+state['issue_id'],labels=labels),state={'stage':'create_intent'})
        and new==dict(name=b.PREFIX+'-base-'+state['issue_id'],labels=labels))
    if spec is not None:
        require(spec['base_sha']==cfg['base']['base_sha'] and spec['manifest_sha256']==cfg['base']['manifest_sha256']
            and bool(spec['baseline_test_sha256'])
            and spec['baseline_test_sha256']==cfg['source']['prepared']['baseline_test_sha256'])


def register(b,source):
    with b.LOCK:
        with b.db() as con:
            seal=maintenance.current(con);require(seal and seal['stage']=='sealed')
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            con.execute('CREATE TABLE IF NOT EXISTS literal_base_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
            row=con.execute('SELECT receipt FROM literal_base_recoveries WHERE source_task=?',(source,)).fetchone()
            if row:return json.loads(row[0])
            cfg,state=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone())
            oldrow=con.execute('SELECT identity,state FROM literal_maintenance_volumes WHERE source_task=?',(source,)).fetchone();require(oldrow)
            old=dict(zip(('identity','state'),map(json.loads,oldrow)))
            for table in ('issue_bases','issue_editables','delivery_routes','test_revision_trials'):
                require(not con.execute('SELECT 1 FROM '+table+' WHERE issue_id=?',(state['issue_id'],)).fetchone())
            copied=completed_copy(con,b,cfg,old['identity'])
        require(not maintenance.native_active(b));fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,state,fx)
        new=dict(name=b.PREFIX+'-base-'+state['issue_id'],labels=old['identity']['labels'])
        qualify(b,cfg,state,old,new)
        require(b.docker('GET','/volumes/'+new['name']) is None)
        volume=b.docker('GET','/volumes/'+old['identity']['name']);require(volume and all(
            volume.get('Labels',{}).get(k)==v for k,v in old['identity']['labels'].items()))
        image=os.environ.get('BROKER_LITERAL_BASE_INSPECTION_IMAGE','')
        require(bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
        payload=dict(Image=image,User='10000:10000',Entrypoint=['python'],Cmd=['/initial_base_inspect.py'],
            Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/','EXPECTED_BASE_MANIFEST_SHA256='+cfg['base']['manifest_sha256']],
            Labels={'delivery-kit.literal-base-recovery':digest(cfg)},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=268435456,PidsLimit=64,Mounts=[dict(Type='volume',Source=old['identity']['name'],Target='/base',ReadOnly=True)]))
        inspected=validation_job.run(b,source,'structure',payload)
        require(inspected['approval'] is False and inspected['exit_code']==0
            and inspected['output_sha256']==hashlib.sha256(inspected['output'].encode()).hexdigest())
        spec=json.loads(inspected['output']);qualify(b,cfg,state,old,new,spec)
        receipt=dict(operation='literal_canonical_base_recovery_v1',config_sha256=digest(cfg),previous_state=state,
            old_intent=old,new_identity=new,completed_copy=copied,inspection=inspected,base_inspection=spec,
            inspection_image=image,maintenance_operation=seal['operation_id'],qualified_at=time.time(),attempt_limit=1,
            source_reset=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
        require(not maintenance.native_active(b))
        with b.db() as con:
            require(maintenance.current(con)==seal)
            actual=con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone()
            require(json.loads(actual[0])==state)
            con.execute('INSERT INTO literal_base_recoveries VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            updated={**state,'stage':'prepare','canonical_base_recovery':digest(receipt),
                'phase_started':receipt['qualified_at'],
                'required_action':'Materialize canonical base from inspected readonly legacy copy; retain original intent'}
            updated.pop('category',None)
            con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return receipt
