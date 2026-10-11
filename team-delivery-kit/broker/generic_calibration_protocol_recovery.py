"""One operator migration of a proved pretool producer protocol failure.

An archived proxy log is diagnostic evidence, not a model decision, read receipt
or delivery approval. No worker endpoint exists. New deployments must preserve
their own rejection receipts; this migration does not invent historical ones.
"""
import hashlib
import json
import time
import uuid
from pathlib import Path
try:
    import controller_maintenance as maintenance,handoffs,generic_calibration_workflow as workflow
except ImportError:
    from broker import controller_maintenance as maintenance,handoffs,generic_calibration_workflow as workflow
from generic_harness_calibration import digest

PROTOCOL='generic-calibration-response-v1'
SOURCES=('calibration_response_contract','artifact_read_evidence','decision_schema','structured_response_contract','model_proxy')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_protocol_recoveries('
        'issue_id TEXT,author_task TEXT,receipt TEXT,PRIMARY KEY(issue_id,author_task))')


def qualified(con,c,s):
    initialize(con)
    row=con.execute('SELECT receipt FROM generic_calibration_protocol_recoveries WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    if not row:raise ValueError('durable protocol migration required')
    receipt=json.loads(row[0])
    if (s.get('protocol_recovery_sha256')!=digest(receipt) or receipt['config_sha256']!=digest(c)
            or receipt['protocol']!=PROTOCOL or receipt['attempt_limit']!=1
            or receipt['execution_authorized'] is not False or receipt['delivery_approval'] is not False):
        raise ValueError('protocol migration drift')
    return receipt


def transition(con,c,state,task,binding,tool_count,event,barrier,namespace,sources,*,now=None):
    initialize(con)
    if (not barrier or barrier.get('stage')!='sealed' or barrier.get('namespace')!=namespace
            or not barrier.get('drained')):raise ValueError('sealed drained operator maintenance required')
    if set(sources)!=set(SOURCES) or any(not isinstance(v,str) or len(v)!=64
            or any(ch not in '0123456789abcdef' for ch in v) for v in sources.values()):
        raise ValueError('installed qualified protocol sources required')
    prior=con.execute('SELECT receipt FROM generic_calibration_protocol_recoveries WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    if prior:
        receipt=qualified(con,c,state)
        if receipt['diagnostic']!=event or receipt['installed_sources']!=sources:
            raise ValueError('migration identity changed; no second attempt')
        return receipt
    diagnostic=event.get('structured_rejection_diagnostic') or {}
    if (state.get('stage')!='blocked' or state.get('category')!='bundle_task_failed'
            or state.get('execution_authorized') is not False or state.get('delivery_approval') is not False
            or state.get('observed_task')!=task.get('id') or state.get('wakeup_id')!=task.get('wakeup_id')
            or task.get('status')!='failed' or task.get('agent_id')!=c['cto'] or task.get('issue_id')!=c['issue_id']
            or task.get('failure_reason')!='agent_error.provider_server_error'
            or binding.get('status')!='closed' or binding.get('task_id')!=task['id']
            or binding.get('issue_id')!=c['issue_id'] or binding.get('agent_id')!=c['cto']
            or binding.get('scope','').split(':')[-2:]!=['planning',task['id']]
            or type(tool_count) is not int or tool_count!=0
            or event.get('event')!='model_proxy_request' or event.get('status')!=502
            or event.get('category')!='structured_decision_response_invalid'
            or event.get('execution_id')!=binding.get('request_id')
            or type(event.get('call_number')) is not int or event['call_number']<1
            or event.get('decision_schema')!='delivery_decision_v1' or event.get('strict_schema') is not True
            or event.get('structured_rejection_category')!='schema_violation'
            or set(diagnostic)!={'version','constraints','upstream_sha256'}
            or diagnostic['version']!='structured-constraint-v1' or diagnostic['constraints']!=['maxItems']
            or not isinstance(diagnostic['upstream_sha256'],str) or len(diagnostic['upstream_sha256'])!=64
            or any(ch not in '0123456789abcdef' for ch in diagnostic['upstream_sha256'])):
        raise ValueError('exact legacy-schema pretool producer failure required')
    for table in ('generic_calibration_proposals','generic_calibration_materializations','generic_calibration_intakes'):
        if con.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() and con.execute(
                'SELECT 1 FROM '+table+' WHERE issue_id=? AND author_task=?',(c['issue_id'],c['author_task'])).fetchone():
            raise ValueError('producer artifacts already exist; migration forbidden')
    parent=handoffs.load(con,c['author_task'])
    data=json.loads(parent['data']) if parent else {}
    if (not parent or parent['issue_id']!=c['issue_id'] or parent['stage']!='test_first_blocked'
            or data.get('calibration_prerequisite')!=state
            or data.get('error')!='generic_calibration_prerequisite:bundle_task_failed'):
        raise ValueError('exact blocked prerequisite handoff required')
    receipt=dict(operation='operator_calibration_protocol_migration_v1',protocol=PROTOCOL,
        config_sha256=digest(c),prior_state=state,diagnostic=event,
        provenance='operator_archived_owned_proxy_log',installed_sources=sources,
        failed_task=task['id'],failed_execution=binding['request_id'],attempt_limit=1,
        author_restarted=False,tests_executed=False,execution_authorized=False,delivery_approval=False,
        maintenance_operation=barrier['operation_id'],at=time.time() if now is None else now)
    token=digest(receipt)
    updated=dict(stage='bundle_dispatch',owner=c['cto'],protocol_recovery_sha256=token,
        execution_authorized=False,delivery_approval=False,
        required_action='One corrected source-bound CTO proposal; preserve failed producer and all delivery gates')
    data.update(calibration_prerequisite=updated,protocol_recovery_sha256=token,
        required_action=updated['required_action'],author_retry_authorized=False,delivery_approval=False)
    data.pop('error',None)
    with con:
        con.execute('INSERT INTO generic_calibration_protocol_recoveries VALUES(?,?,?)',
            (c['issue_id'],c['author_task'],json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(updated,sort_keys=True),c['issue_id'],c['author_task']))
        handoffs.save(con,c['author_task'],c['issue_id'],'test_first_validation_pending',c['cto'],data,
            receipt['at'],commit=False)
    return receipt


def migrate(b,issue,author,operation,archive_sha256):
    """Operator-only entrypoint; archive is private controller storage, not payload."""
    for value in (issue,author,operation):
        if str(uuid.UUID(value))!=value:raise ValueError('canonical migration identity required')
    if maintenance.native_active(b):raise ValueError('native tasks must be idle')
    import importlib.util
    expected={name:hashlib.sha256(Path(importlib.util.find_spec(name).origin).read_bytes()).hexdigest() for name in SOURCES}
    # Fixed local probe: no agent-supplied command, model call or arbitrary file.
    try:import provider_diagnosis_recovery as provider
    except ImportError:from broker import provider_diagnosis_recovery as provider
    proxy=provider.proxy_info(b)
    script='''import sys;sys.path.insert(0,"/")
import hashlib,json,importlib.util
from pathlib import Path
import calibration_response_contract as c,model_proxy as m
p='/evidence/candidate/tests/test_probe.py'
body=dict(model=m.MODEL,messages=[dict(role='user',content='DELIVERY_STRUCTURED_DECISION_V1:technical\\nDELIVERY_TYPED_DECISION_V1\\nDELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_old.py\\n'+c.capsule(c.context('bundle',[p],'a'*64)))],tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
r=m.validate_request(body)
assert r['tool_choice']['function']['name']=='read_file' and 'response_format' not in r
print(json.dumps({n:hashlib.sha256(Path(importlib.util.find_spec(n).origin).read_bytes()).hexdigest() for n in ('calibration_response_contract','artifact_read_evidence','decision_schema','structured_response_contract','model_proxy')}))
'''
    entry=b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,AttachStderr=False,
        Tty=True,Cmd=['python','-c',script]))
    conn=b.DockerConnection('localhost',timeout=10)
    try:
        conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),{'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(4097)
        if response.status!=200 or len(raw)>4096:raise ValueError('bounded installed protocol proof required')
    finally:conn.close()
    outcome=b.docker('GET','/exec/'+entry['Id']+'/json')
    if outcome.get('Running') or outcome.get('ExitCode')!=0 or json.loads(raw)!=expected:
        raise ValueError('proxy/controller protocol source mismatch')
    with b.LOCK:
        fx=workflow.Effects(b)
        with b.db() as con:
            row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',(issue,author)).fetchone()
            if not row:raise ValueError('existing frozen calibration required')
            c,state=map(json.loads,row)
        fx.verify(c)
        workflow.request(b,issue,author) # Revalidates original completed author and immutable copy identity.
        failed=qualified_receipt(b,c)['failed_task'] if state.get('protocol_recovery_sha256') else state['observed_task']
        task=fx.plans.task(failed,c['cto'])
        path=b.STATE/'protocol-migrations'/(task['id']+'.json')
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file() or path.stat().st_size>8192:
            raise ValueError('bounded private operator archive required')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=archive_sha256:raise ValueError('operator archive hash drift')
        events=json.loads(raw)
        if not isinstance(events,list) or len(events)!=1:raise ValueError('one exact archived rejection required')
        with b.db() as con:
            maintenance.transaction(con);barrier=maintenance.current(con)
            if not barrier or barrier['operation_id']!=operation:raise ValueError('exact sealed operation required')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing','active')").fetchone():
                raise ValueError('active leases forbid migration')
            current=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',(issue,author)).fetchone()
            if list(map(json.loads,current))!=[c,state]:raise ValueError('workflow changed during qualification')
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(task['id'],)).fetchall()
            if len(rows)!=1:raise ValueError('one exact closed binding required')
            binding=dict(rows[0])
            tools=con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(binding['request_id'],)).fetchone()[0]
            return transition(con,c,state,task,binding,tools,events[0],barrier,b.PREFIX,expected)


def qualified_receipt(b,c):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT receipt FROM generic_calibration_protocol_recoveries WHERE issue_id=? AND author_task=?',(c['issue_id'],c['author_task'])).fetchone()
        if not row:raise ValueError('missing prior migration')
        return json.loads(row[0])
