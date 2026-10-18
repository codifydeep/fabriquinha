"""One qualified planner-only recovery after a proven local schema rejection.

No worker endpoint, source reset, author retry, receipt replay or delivery grant.
The fixed installed proxy reads its own rejection ledger and runs the corrected
request contract offline. A second recovery cannot renew the same allowance.
"""
import hashlib
import json
from generic_harness_calibration import digest,require
from proxy_request_rejections import record
try:
    import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
    import controller_maintenance as maintenance,native_scope_note
    from provider_access_recovery import ERROR
except ImportError:
    from broker import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
    from broker import controller_maintenance as maintenance,native_scope_note
    from broker.provider_access_recovery import ERROR

PROBE='''import sys,json;sys.path.insert(0,"/")
import model_proxy as m,proxy_request_rejections as r
from pathlib import Path
from decision_schema import apply as schema
from typed_decision_contract import apply as typed
from generic_harness_calibration import digest
path=Path(m.COUNTER_PATH);before=json.loads(path.read_text())["calls"]
note=sys.argv[2];body=typed(schema(dict(messages=[dict(role="user",content=note)],tools=[])))
policy=digest(dict(note=note,contract=body["tools"][0]["function"]["parameters"]))
print(json.dumps(dict(rejections=r.read(m.COUNTER_PATH,sys.argv[1]),policy_sha256=policy,
 calls_before=before,calls_after=json.loads(path.read_text())["calls"])))
'''


def qualify(cfg,state,task,binding,proof):
    expected=lane.expected_note(cfg,state,'plan')
    previous=expected.replace('DELIVERY_TYPED_DECISION_V1\n',
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\n',1)
    require(state.get('stage')=='blocked' and state.get('category')=='native_plan_failed'
        and set(state.get('decisions',{}))=={'triage'} and state.get('revision')==0
        and not state.get('history') and not state.get('author_task') and not state.get('prepared')
        and not state.get('preflight_recovery') and state['source_reset'] is False
        and state['delivery_approval'] is False and state['functional_red'] is False
        and task.get('status')=='failed' and task.get('error')==ERROR
        and task.get('agent_id')==cfg['cto'] and task.get('issue_id')==state['issue_id']
        and task.get('wakeup_id')==state['wakeup_id'] and task['id']!=cfg['source']['author_task']
        and native_scope_note.canonical(task.get('handoff_note',''),state['wakeup_id'])==previous
        and binding.get('status')=='closed' and binding.get('task_id')==task['id']
        and binding.get('scope','').split(':')[-2:]==['planning',task['id']] and binding.get('agent_id')==cfg['cto']
        and binding.get('issue_id')==state['issue_id'] and binding.get('tool_count')==0
        and proof.get('policy_sha256')==flow.preflight_plan(cfg,state)
        and type(proof.get('calls_before')) is int and proof['calls_before']>=0
        and proof.get('calls_after')==proof['calls_before']
        and isinstance(proof.get('rejections'),list) and len(proof['rejections'])==1)
    rejection=proof['rejections'][0];record(None,rejection)
    require(rejection['execution_id']==binding['request_id'] and rejection['stage']=='contract'
        and rejection.get('origin',{}).get('module')=='typed_decision_contract'
        and rejection['exception_type']=='ValueError'
        and rejection['error_sha256']==hashlib.sha256(b'observed non-approving test diagnosis contract required').hexdigest())
    return dict(operation='literal_plan_schema_recovery_v1',failed_task=task['id'],
        execution_id=binding['request_id'],previous_state=state,proxy_proof=proof,
        config_sha256=digest(cfg),attempt_limit=1,author_retry_authorized=False,
        source_reset=False,execution_authorized=False,delivery_approval=False)


def register(b,source,failed_task):
    with b.LOCK:
        with b.db() as con:
            seal=maintenance.current(con);require(seal and seal['stage']=='sealed')
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            con.execute('CREATE TABLE IF NOT EXISTS literal_plan_schema_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
            previous=con.execute('SELECT receipt FROM literal_plan_schema_recoveries WHERE source_task=?',(source,)).fetchone()
            if previous:
                receipt=json.loads(previous[0]);require(receipt['failed_task']==failed_task);return receipt
            cfg,state=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone())
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(failed_task,)).fetchall()
            require(len(rows)==1);binding=dict(rows[0])
            binding['tool_count']=con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',
                (binding['request_id'],)).fetchone()[0]
        require(not maintenance.native_active(b));fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,state,fx)
        task=fx.plans.task(failed_task,cfg['cto'])
        proof,image=fx.old.proxy_read(PROBE,[binding['request_id'],flow.instruction(cfg,state,'plan')])
        receipt=qualify(cfg,state,task,binding,proof)
        receipt.update(proxy_image=image,maintenance_operation=seal['operation_id'])
        require(not maintenance.native_active(b))
        with b.db() as con:
            require(maintenance.current(con)==seal)
            actual=con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone()
            require(json.loads(actual[0])==state)
            updated={**state,'stage':'plan_dispatch','owner':cfg['cto'],
                'preflight_recovery':digest(receipt),'required_action':'New CTO scope decision after qualified local contract correction; original failure retained'}
            for key in ('category','wakeup_id','marker','phase_started'):updated.pop(key,None)
            con.execute('INSERT INTO literal_plan_schema_recoveries VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return receipt
