"""Once-only observation recovery of an already-created empty-mount probe.

No Docker mutation, native dispatch or author budget renewal occurs here. The
ordinary job runner alone may subsequently start the same verified container.
"""
import hashlib
import json
import time
from pathlib import Path

from generic_harness_calibration import digest, require
try:
    import calibration_capability_review as capability
    import controller_maintenance as maintenance
    import validation_job as jobs
    import test_first_job as isolation
except ImportError:
    from broker import calibration_capability_review as capability
    from broker import controller_maintenance as maintenance
    from broker import validation_job as jobs
    from broker import test_first_job as isolation


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_capability_mount_recoveries('
        'issue_id TEXT,author_task TEXT,receipt TEXT,PRIMARY KEY(issue_id,author_task))')


def identity(b,cfg):
    task=cfg['capability_request']['task_id']
    payload=jobs.grouped_create('POST','/containers/create?name=validation',capability.measurement_payload(cfg),b.PREFIX)
    key=jobs.digest(dict(task=task,kind='structure',payload=payload))
    name=b.PREFIX+'-validation-job-'+task+'-'+key[:12]
    payload={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
    return key,dict(task=task,kind='structure',name=name,payload=payload)


def qualified(con,cfg,state):
    initialize(con);c=cfg['source']
    row=con.execute('SELECT receipt FROM calibration_capability_mount_recoveries WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone();require(row)
    r=json.loads(row[0])
    require(r['operation']=='empty_mount_observation_v1' and r['config_sha256']==digest(cfg)
        and state['mount_observation_recovery_sha256']==digest(r)
        and all(r[k] is False for k in ('create_replayed','start_replayed','author_retry_authorized',
            'source_reset','retry_budget_reset','delivery_approval'))
        and r['observation_window_requalified'] is True
        and r['previous_state']['stage']=='blocked'
        and r['previous_state']['category']=='capability_evidence_rejected'
        and r['previous_job_state']['stage']=='create_intent'
        and r['previous_job_state']['approval'] is False
        and r['new_deadline']==r['observed_at']+600)
    job=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(r['job_key'],)).fetchone();require(job)
    actual,s=map(json.loads,job)
    require(actual==r['identity'] and s.get('container_id')==r['container_id']
        and s['deadline']==r['new_deadline'] and s['approval'] is False)
    return r


def recover(b,issue,author,operation,*,now=None):
    now=time.time() if now is None else now
    with b.LOCK,b.db() as con:
        initialize(con)
        maintenance.transaction(con)
        barrier=maintenance.current(con)
        require(barrier and barrier['stage']=='sealed' and barrier.get('drained') is True
            and barrier['operation_id']==operation and barrier['namespace']==b.PREFIX)
        require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone())
        row=con.execute('SELECT config,state FROM calibration_capability_reviews WHERE issue_id=? AND author_task=?',
            (issue,author)).fetchone();require(row);cfg,s=map(json.loads,row)
        prior=con.execute('SELECT receipt FROM calibration_capability_mount_recoveries WHERE issue_id=? AND author_task=?',
            (issue,author)).fetchone()
        if prior:
            r=qualified(con,cfg,s);require(r['maintenance_operation']==operation);return r
        require(s['stage']=='blocked' and s['category']=='capability_evidence_rejected'
            and not any(k in s for k in ('issue_id','wakeup_id','measurement','measurement_job','decision','receipt'))
            and all(s.get(k) is False for k in capability.FALSE_FLAGS))
        capability.Effects(b).verify(cfg)  # Reauthenticate the original native decisions, never dispatch.
        key,expected=identity(b,cfg)
        job=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone();require(job)
        actual,old=map(json.loads,job)
        require(actual==expected and old['stage']=='create_intent' and old['approval'] is False
            and not old.get('container_id') and not old.get('result'))
        info=b.docker('GET','/containers/'+expected['name']+'/json');require(info)
        st=info['State']
        require(st['Status']=='created' and st['Running'] is False and st['Pid']==0
            and st['StartedAt'].startswith('0001-') and st['FinishedAt'].startswith('0001-')
            and info.get('RestartCount',0)==0 and not info.get('ExecIDs')
            and info['HostConfig'].get('Mounts') is None and info.get('Mounts')==[]
            and expected['payload']['HostConfig']['Mounts']==[])
        # Demonstrate precisely the old failure, then verify the entire unchanged policy.
        try:isolation.normalized_mounts(info['HostConfig'].get('Mounts'))
        except ValueError:pass
        else:raise ValueError('old empty-mount rejection not reproduced')
        isolation.verify(b,info,expected['payload'])
        r=dict(operation='empty_mount_observation_v1',config_sha256=digest(cfg),
            previous_state=s,previous_job_state=old,identity=expected,job_key=key,
            container_id=info['Id'],maintenance_operation=operation,observed_at=now,new_deadline=now+600,
            verifier_sha256=hashlib.sha256(Path(isolation.__file__).read_bytes()).hexdigest(),
            mounts_observed=dict(host_mounts=None,actual_mounts=[]),observation_window_requalified=True,
            **{k:False for k in ('create_replayed','start_replayed','author_retry_authorized',
                'source_reset','retry_budget_reset','delivery_approval')})
        observed={**old,'stage':'created','container_id':info['Id'],'deadline':r['new_deadline']}
        resumed={**s,'stage':'measure','phase_started':now,'mount_observation_recovery_sha256':digest(r)}
        resumed.pop('category',None)
        resumed['required_action']='Observe the same verified never-started probe; no repeated create'
        con.execute('SAVEPOINT empty_mount_recovery')
        try:
            con.execute('INSERT INTO calibration_capability_mount_recoveries VALUES(?,?,?)',
                (issue,author,json.dumps(r,sort_keys=True)))
            con.execute('UPDATE validation_jobs SET state=? WHERE job_key=?',(json.dumps(observed,sort_keys=True),key))
            con.execute('UPDATE calibration_capability_reviews SET state=? WHERE issue_id=? AND author_task=?',
                (json.dumps(resumed,sort_keys=True),issue,author))
            qualified(con,cfg,resumed)
            con.execute('RELEASE SAVEPOINT empty_mount_recovery')
        except BaseException:
            con.execute('ROLLBACK TO SAVEPOINT empty_mount_recovery')
            con.execute('RELEASE SAVEPOINT empty_mount_recovery');raise
        return r
