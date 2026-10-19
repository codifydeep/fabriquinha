"""One qualification of a legacy failed protocol for changes-only review.

Authenticate the completed immutable job from its journal. Never rerun a helper,
relax the original assertion, approve the artifact or reset author attempts.
"""
import hashlib
import json
from generic_harness_calibration import digest,require
from literal_inspection_assessment import assess
from docker_grouping import grouped_create
try:
    import literal_maintenance_effects as lane,literal_maintenance_workflow as flow,controller_maintenance as maintenance
    from test_first_job import digest as job_digest
except ImportError:
    from broker import literal_maintenance_effects as lane,literal_maintenance_workflow as flow,controller_maintenance as maintenance
    from broker.test_first_job import digest as job_digest


def inspection_identity(b,cfg,s):
    payload=grouped_create('POST','/containers/create?name=validation',lane.inspection_payload(cfg,s),b.PREFIX)
    task=s['author_task'];key=job_digest(dict(task=task,kind='structure',payload=payload))
    expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
    return key,dict(task=task,kind='structure',name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)


def completed_inspection(con,b,cfg,s):
    key,identity=inspection_identity(b,cfg,s)
    row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone();require(row)
    recorded,job=map(json.loads,row);require(recorded==identity and job['stage']=='complete')
    result=job['result'];require(result==s['inspection']['validation_job'] and result['approval'] is False
        and result['exit_code']==0 and result['container_id']==job['container_id']
        and result['validation_job_key']==key and result['validation_contract_sha256']==job_digest(identity)
        and result['output_sha256']==hashlib.sha256(result['output'].encode()).hexdigest()
        and {**json.loads(result['output']),'validation_job':result}==s['inspection'])
    return result


def qualify(cfg,s,author,binding,snapshot):
    require(s.get('stage')=='blocked' and s.get('category')=='maintenance_sensitivity_failed'
        and s.get('revision')==0 and not s.get('history') and not s.get('failed_inspection_review')
        and set(s.get('decisions',{}))=={'triage','plan','permit'}
        and s['source_reset'] is False and s['functional_red'] is False and s['delivery_approval'] is False
        and author.get('id')==s['author_task'] and author.get('status')=='completed'
        and author.get('agent_id')==cfg['author'] and author.get('issue_id')==s['issue_id']
        and author.get('wakeup_id')==s['author_wakeup']
        and binding.get('task_id')==s['author_task'] and binding.get('agent_id')==cfg['author']
        and binding.get('issue_id')==s['issue_id'] and binding.get('status')=='closed'
        and binding.get('scope','').split(':')[-2:]==['implementation',s['author_task']]
        and snapshot.get('task_id')==s['author_task'] and snapshot.get('status')=='complete'
        and snapshot.get('volume')==s['snapshot']['volume'])
    facts=assess(cfg,s['inspection']);require(facts['all_protocol_checks_passed'] is False)
    return facts


def register(b,source):
    with b.LOCK:
        with b.db() as con:
            seal=maintenance.current(con);require(seal and seal['stage']=='sealed')
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            con.execute('CREATE TABLE IF NOT EXISTS literal_failed_inspection_reviews(source_task TEXT PRIMARY KEY,receipt TEXT)')
            row=con.execute('SELECT receipt FROM literal_failed_inspection_reviews WHERE source_task=?',(source,)).fetchone()
            if row:return json.loads(row[0])
            cfg,s=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone())
            checked=completed_inspection(con,b,cfg,s)
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(s['author_task'],)).fetchall();require(len(rows)==1)
            binding=dict(rows[0]);snapshot=con.execute('SELECT * FROM snapshots WHERE task_id=?',(s['author_task'],)).fetchone();require(snapshot)
        require(not maintenance.native_active(b));fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
        fx.validate_inspection(cfg,s,s['inspection'])
        facts=qualify(cfg,s,fx.plans.task(s['author_task'],cfg['author']),binding,dict(snapshot))
        labels=(b.docker('GET','/volumes/'+s['snapshot']['volume']) or {}).get('Labels',{})
        require(labels.get('delivery-kit.owner')==b.OWNER and labels.get('delivery-kit.source-task')==s['author_task'])
        note=flow.instruction(cfg,s,'review');require(len(note)+512+len(source)+100<=4000)
        receipt=dict(operation='literal_failed_protocol_changes_review_v1',config_sha256=digest(cfg),previous_state=s,
            validation_job=checked,assessment=facts,review_note_sha256=hashlib.sha256(note.encode()).hexdigest(),
            snapshot=dict(snapshot),closed_author_binding=binding,maintenance_operation=seal['operation_id'],
            attempt_limit=1,author_retry_authorized=False,source_reset=False,execution_authorized=False,delivery_approval=False)
        require(not maintenance.native_active(b))
        with b.db() as con:
            con.execute('BEGIN IMMEDIATE');require(maintenance.current(con)==seal)
            require(json.loads(con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone()[0])==s)
            con.execute('INSERT INTO literal_failed_inspection_reviews VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            updated={**s,'stage':'review_dispatch','owner':cfg['reviewer'],'failed_inspection_review':digest(receipt),
                'required_action':'Independent changes-only review of recorded protocol failure; approval remains blocked'}
            for key in ('category','wakeup_id','marker','phase_started'):updated.pop(key,None)
            con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return receipt
