"""Controller-only primitives for one qualified v1-to-v2 capability change.

Caller must authenticate sealed maintenance, a real readonly seam probe, closed
native task/binding and original author/copy identity. No agent-facing API and
no claim to reconstruct the lost producer response. Native wrapper is separate.
"""
import json
import re
import time
from generic_harness_calibration import digest,relative,require
try:import handoffs
except ImportError:from broker import handoffs

PROTOCOL='generic-calibration-capability-v2'


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_capability_recoveries('
        'issue_id TEXT,author_task TEXT,receipt TEXT,PRIMARY KEY(issue_id,author_task))')


def qualified(con,c,state):
    initialize(con)
    row=con.execute('SELECT receipt FROM generic_calibration_capability_recoveries WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    require(row is not None);receipt=json.loads(row[0])
    require(receipt['protocol']==PROTOCOL and receipt['new_config_sha256']==digest(c)
        and c.get('calibration_engine')=='unittest_path_fixtures_v2' and receipt['attempt_limit']==1
        and state.get('capability_recovery_sha256')==digest(receipt)
        and all(receipt[k] is False for k in ('author_restarted','tests_executed','execution_authorized','delivery_approval')))
    return receipt


def seam(proof,c):
    require(isinstance(proof,dict) and set(proof)=={'operation','candidate_manifest_sha256','test_sha256',
        'paths','product_sha256','tests_executed','execution_authorized','delivery_approval'})
    require(proof['operation']=='generic_calibration_multipath_seam_v1'
        and proof['candidate_manifest_sha256']==c['prepared']['manifest_sha256']
        and proof['test_sha256']==c['prepared']['test_sha256']
        and all(proof[k] is False for k in ('tests_executed','execution_authorized','delivery_approval')))
    paths=proof['paths'];products=proof['product_sha256']
    require(isinstance(paths,dict) and set(paths)==set(proof['test_sha256']) and isinstance(products,dict))
    declared=set();multiple=False
    for targets in paths.values():
        require(isinstance(targets,dict) and len(targets)<=16)
        for attribute,path in targets.items():
            require(isinstance(attribute,str) and bool(re.fullmatch('[A-Z][A-Z0-9_]{0,119}',attribute)))
            relative(path);require(path not in proof['test_sha256']);declared.add(path)
        multiple|=len(targets)>=2 and len(set(targets.values()))==len(targets)
    require(multiple and set(products)==declared)
    for sha in products.values():require(isinstance(sha,str) and bool(re.fullmatch('[a-f0-9]{64}',sha)))


def transition(con,c,state,task,binding,proof,barrier,namespace,*,now=None,probe_evidence=None):
    initialize(con)
    require(barrier and barrier.get('stage')=='sealed' and barrier.get('drained') is True
        and barrier.get('namespace')==namespace)
    prior=con.execute('SELECT receipt FROM generic_calibration_capability_recoveries WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    if prior:
        receipt=qualified(con,c,state);require(receipt['seam_proof']==proof)
        return receipt # Never rewind a later failure or repeat an intervention.
    require(c.get('calibration_engine','unittest_path_fixture_v1')=='unittest_path_fixture_v1'
        and state.get('stage')=='blocked' and state.get('category')=='bundle_task_failed'
        and task.get('id')==state.get('observed_task') and task.get('status')=='failed'
        and task.get('agent_id')==c['cto'] and task.get('issue_id')==c['issue_id']
        and task.get('wakeup_id')==state.get('wakeup_id')
        and binding.get('status')=='closed' and binding.get('task_id')==task['id']
        and binding.get('agent_id')==c['cto'] and binding.get('issue_id')==c['issue_id']
        and binding.get('scope','').split(':')[-2:]==['planning',task['id']])
    seam(proof,c)
    row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    require(row and list(map(json.loads,row))==[c,state])
    for table in ('generic_calibration_proposals','generic_calibration_materializations','generic_calibration_intakes'):
        if con.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
            require(not con.execute('SELECT 1 FROM '+table+' WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone())
    parent=handoffs.load(con,c['author_task']);data=json.loads(parent['data']) if parent else {}
    require(parent and parent['issue_id']==c['issue_id'] and parent['stage']=='test_first_blocked'
        and data.get('calibration_prerequisite')==state
        and data.get('error')=='generic_calibration_prerequisite:bundle_task_failed')
    updated_config={**c,'calibration_engine':'unittest_path_fixtures_v2'}
    receipt=dict(operation='operator_calibration_capability_migration_v2',protocol=PROTOCOL,
        prior_config=c,prior_state=state,new_config_sha256=digest(updated_config),seam_proof=proof,
        probe_evidence=probe_evidence,
        failed_task=task['id'],failed_execution=binding['request_id'],attempt_limit=1,
        reason='multiple existing snapshot Path globals require independent positive references; not a reconstructed failure cause',
        author_restarted=False,tests_executed=False,execution_authorized=False,delivery_approval=False,
        maintenance_operation=barrier['operation_id'],at=time.time() if now is None else now)
    token=digest(receipt)
    updated=dict(stage='bundle_dispatch',owner=c['cto'],capability_recovery_sha256=token,
        execution_authorized=False,delivery_approval=False,required_action='One v2 CTO proposal; preserve author and every delivery gate')
    data.update(calibration_prerequisite=updated,capability_recovery_sha256=token,
        required_action=updated['required_action'],author_retry_authorized=False,delivery_approval=False)
    data.pop('error',None)
    with con:
        con.execute('INSERT INTO generic_calibration_capability_recoveries VALUES(?,?,?)',
            (c['issue_id'],c['author_task'],json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE generic_calibration_workflows SET config=?,state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(updated_config,sort_keys=True),json.dumps(updated,sort_keys=True),c['issue_id'],c['author_task']))
        handoffs.save(con,c['author_task'],c['issue_id'],'test_first_validation_pending',c['cto'],data,receipt['at'],commit=False)
    return receipt


def migrate(b,issue,author,operation):
    """Operator-only: collect real native/SQLite/Docker facts, never payload claims.

Calling again observes the original probe/receipt. It does not repeat uncertain
Docker effects, reset any ledger, restart the author or approve delivery.
"""
    import uuid
    try:import controller_maintenance as maintenance,generic_calibration_workflow as workflow,generic_calibration_seam_job as jobs,generic_calibration_registration as registration,generic_calibration_gate as gate
    except ImportError:from broker import controller_maintenance as maintenance,generic_calibration_workflow as workflow,generic_calibration_seam_job as jobs,generic_calibration_registration as registration,generic_calibration_gate as gate
    for value in (issue,author,operation):require(str(uuid.UUID(value))==value)
    require(not maintenance.native_active(b))
    with b.LOCK:
        with b.db() as con:
            maintenance.transaction(con);barrier=maintenance.current(con)
            require(barrier and barrier['operation_id']==operation and barrier['stage']=='sealed'
                and barrier['namespace']==b.PREFIX and barrier.get('drained') is True)
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
                (issue,author)).fetchone();require(row is not None);c,state=map(json.loads,row)
            require(c['issue_id']==issue and c['author_task']==author)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            require(route['cto']==c['cto'] and route['techlead']==c['reviewer']
                and len({route['author'],c['cto'],c['reviewer']})==3)
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (author,)).fetchall()
            require(len(rows)==1);author_binding=dict(rows[0])
            require(author_binding['status']=='closed' and author_binding['agent_id']==route['author']
                and author_binding['issue_id']==issue)
            copied=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(author+':copy',)).fetchone()
            require(copied is not None)
            registration.copy_matches(dict(policy=dict(candidate_manifest_sha256=c['prepared']['manifest_sha256'],
                test_sha256=c['prepared']['test_sha256']),context=dict(author_task=author,candidate_volume=c['candidate_volume'])),
                *map(json.loads,copied))
            initialize(con)
            existing=con.execute('SELECT receipt FROM generic_calibration_capability_recoveries WHERE issue_id=? AND author_task=?',
                (issue,author)).fetchone()
        fx=workflow.Effects(b);fx.verify(c)
        authored=fx.plans.task(author,route['author']);gate.require_author_scope(author_binding,authored)
        if existing:
            with b.db() as con:return qualified(con,c,state) # No second native intervention.
        require(state.get('stage')=='blocked' and state.get('category')=='bundle_task_failed')
        task=fx.plans.task(state['observed_task'],c['cto'])
        with b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (task['id'],)).fetchall()
            require(len(rows)==1);binding=dict(rows[0])
            require(binding['status']=='closed' and task.get('status')=='failed'
                and binding['agent_id']==c['cto'] and binding['issue_id']==issue
                and binding.get('scope','').split(':')[-2:]==['planning',task['id']]
                and task.get('agent_id')==c['cto'] and task.get('issue_id')==issue
                and task.get('wakeup_id')==state.get('wakeup_id'))
            result=jobs.run(b,con,c)
            require(result['approval'] is False and type(result['exit_code']) is int and result['exit_code']==0)
            # The job validates actual output bytes and snapshot hashes. Preserve
            # the exact observation as part of the migration's durable receipt.
            proof=json.loads(result['output']);seam(proof,c)
            image=jobs.payload(b,c)['Image']
        require(not maintenance.native_active(b))
        with b.db() as con:
            maintenance.transaction(con);current=maintenance.current(con)
            require(current==barrier)
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
                (issue,author)).fetchone();require(row and list(map(json.loads,row))==[c,state])
            return transition(con,c,state,task,binding,proof,current,b.PREFIX,
                probe_evidence=dict(image=image,container_id=result['container_id'],result_sha256=digest(result)))
