"""One qualified local read-contract repair; no worker-facing recovery API.

The proxy ledger proves a particular pre-upstream rejection, not the absence of
all historical model calls. Prior protocol/capability ledgers remain untouched.
"""
import hashlib
import json
import re
import time
from generic_harness_calibration import digest,require
try:import handoffs,generic_calibration_capability_recovery as capability
except ImportError:from broker import handoffs,generic_calibration_capability_recovery as capability

PROTOCOL='generic-calibration-local-read-repair-v1'
SOURCES=('deterministic_read_dispatch','calibration_response_contract','artifact_read_evidence',
    'artifact_response_contract','decision_schema')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_local_recoveries('
        'issue_id TEXT,author_task TEXT,receipt TEXT,PRIMARY KEY(issue_id,author_task))')


def qualified(con,c,state):
    initialize(con)
    row=con.execute('SELECT receipt FROM generic_calibration_local_recoveries WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone();require(row is not None)
    r=json.loads(row[0])
    require(r['protocol']==PROTOCOL and r['config_sha256']==digest(c) and r['attempt_limit']==1
        and state.get('local_recovery_sha256')==digest(r)
        and all(r[k] is False for k in ('author_restarted','tests_executed','execution_authorized','delivery_approval')))
    return r


def transition(con,c,state,task,binding,tool_count,rejection,proof,barrier,namespace,*,now=None):
    initialize(con)
    require(barrier and barrier.get('stage')=='sealed' and barrier.get('drained') is True
        and barrier.get('namespace')==namespace)
    if con.execute('SELECT 1 FROM generic_calibration_local_recoveries WHERE issue_id=? AND author_task=?',
            (c['issue_id'],c['author_task'])).fetchone():return qualified(con,c,state)
    capability.qualified(con,c,state)
    require(state.get('stage')=='blocked' and state.get('category')=='bundle_task_failed'
        and state.get('execution_authorized') is False and state.get('delivery_approval') is False
        and task.get('id')==state.get('observed_task') and task.get('wakeup_id')==state.get('wakeup_id')
        and task.get('status')=='failed' and task.get('agent_id')==c['cto'] and task.get('issue_id')==c['issue_id']
        and binding.get('status')=='closed' and binding.get('task_id')==task['id']
        and binding.get('agent_id')==c['cto'] and binding.get('issue_id')==c['issue_id']
        and binding.get('scope','').split(':')[-2:]==['planning',task['id']]
        and type(tool_count) is int and tool_count==0)
    require(set(rejection)=={'operation','execution_id','request_sha256','stage','origin','exception_type',
        'error_sha256','retry_authorized','delivery_approval'})
    origin=rejection['origin'] or {}
    require(rejection['operation']=='local_request_rejection_v1' and rejection['execution_id']==binding['request_id']
        and rejection['stage']=='read_dispatch' and rejection['exception_type']=='ValueError'
        and origin.get('module')=='deterministic_read_dispatch' and type(origin.get('line')) is int and origin['line']>0
        and rejection['error_sha256']==hashlib.sha256(b'invalid deterministic read contract').hexdigest()
        and bool(re.fullmatch('[a-f0-9]{64}',str(rejection['request_sha256'])))
        and rejection['retry_authorized'] is False and rejection['delivery_approval'] is False)
    require(set(proof)=={'operation','passed','source_sha256','sources','proxy_image','delivery_approval'}
        and proof['operation']=='calibration_read_qualification_v1' and proof['passed'] is True
        and proof['delivery_approval'] is False and proof['source_sha256']==digest(c)
        and bool(re.fullmatch('sha256:[a-f0-9]{64}',str(proof['proxy_image'])))
        and set(proof['sources'])==set(SOURCES)
        and all(bool(re.fullmatch('[a-f0-9]{64}',str(v))) for v in proof['sources'].values()))
    row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone();require(row and list(map(json.loads,row))==[c,state])
    for table in ('generic_calibration_proposals','generic_calibration_materializations','generic_calibration_intakes'):
        if con.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
            require(not con.execute('SELECT 1 FROM '+table+' WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone())
    parent=handoffs.load(con,c['author_task']);data=json.loads(parent['data']) if parent else {}
    require(parent and parent['issue_id']==c['issue_id'] and parent['stage']=='test_first_blocked'
        and data.get('calibration_prerequisite')==state
        and data.get('error')=='generic_calibration_prerequisite:bundle_task_failed')
    receipt=dict(operation='operator_calibration_local_repair_v1',protocol=PROTOCOL,config_sha256=digest(c),
        prior_state=state,rejection=rejection,qualification=proof,failed_task=task['id'],failed_execution=binding['request_id'],
        attempt_limit=1,author_restarted=False,tests_executed=False,execution_authorized=False,delivery_approval=False,
        maintenance_operation=barrier['operation_id'],at=time.time() if now is None else now)
    updated=dict(stage='bundle_dispatch',owner=c['cto'],capability_recovery_sha256=state['capability_recovery_sha256'],
        local_recovery_sha256=digest(receipt),execution_authorized=False,delivery_approval=False,
        required_action='One CTO proposal after qualified local proxy repair; no author retry or delivery waiver')
    data.update(calibration_prerequisite=updated,local_recovery_sha256=digest(receipt),
        author_retry_authorized=False,delivery_approval=False,required_action=updated['required_action']);data.pop('error',None)
    with con:
        con.execute('INSERT INTO generic_calibration_local_recoveries VALUES(?,?,?)',
            (c['issue_id'],c['author_task'],json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(updated,sort_keys=True),c['issue_id'],c['author_task']))
        handoffs.save(con,c['author_task'],c['issue_id'],'test_first_validation_pending',c['cto'],data,receipt['at'],commit=False)
    return receipt


PROXY_PROBE='''import sys,json,hashlib,importlib.util
from pathlib import Path
sys.path.insert(0,"/")
import model_proxy as m,calibration_response_contract as c,deterministic_read_dispatch as d
import proxy_request_rejections as rejections
from artifact_response_contract import validate
from artifact_read_evidence import observations
execution,source=sys.argv[1:]
v=c.context("bundle",["/evidence/candidate/tests/test_fixture.py"],source,engine="unittest_path_fixtures_v2")
b=m.validate_request(dict(model=m.MODEL,stream=False,messages=[dict(role="user",content="DELIVERY_DETERMINISTIC_READ_V1\\n"+c.capsule(v))],tools=[dict(type="function",function=dict(name="read_file",parameters={}))]))
r=d.make(b,execution);validate(b,r["data"],r["media_type"])
assert observations([dict(role="assistant",content=r["data"].decode())],wire=True)=={}
names=("deterministic_read_dispatch","calibration_response_contract","artifact_read_evidence","artifact_response_contract","decision_schema")
print(json.dumps(dict(rejections=rejections.read(m.COUNTER_PATH,execution),sources={n:hashlib.sha256(Path(importlib.util.find_spec(n).origin).read_bytes()).hexdigest() for n in names},passed=True)))
'''


def migrate(b,issue,author,operation):
    """Collect native facts and proxy-owned evidence under sealed maintenance."""
    import uuid
    import importlib.util
    from pathlib import Path
    try:import controller_maintenance as maintenance,generic_calibration_workflow as workflow,provider_diagnosis_recovery as provider
    except ImportError:from broker import controller_maintenance as maintenance,generic_calibration_workflow as workflow,provider_diagnosis_recovery as provider
    for value in (issue,author,operation):require(str(uuid.UUID(value))==value)
    # Reuse the authenticated original-author/copy/route check. Since the
    # capability receipt must already exist, this cannot apply it again.
    with b.db() as con:
        require(con.execute("SELECT 1 FROM sqlite_master WHERE name='generic_calibration_capability_recoveries'").fetchone())
        require(con.execute('SELECT 1 FROM generic_calibration_capability_recoveries WHERE issue_id=? AND author_task=?',
            (issue,author)).fetchone())
    capability.migrate(b,issue,author,operation)
    with b.LOCK:
        with b.db() as con:
            maintenance.transaction(con);barrier=maintenance.current(con)
            require(barrier and barrier['operation_id']==operation and barrier['stage']=='sealed' and barrier.get('drained') is True)
            row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
                (issue,author)).fetchone();require(row is not None);c,state=map(json.loads,row)
            initialize(con)
            if con.execute('SELECT 1 FROM generic_calibration_local_recoveries WHERE issue_id=? AND author_task=?',
                    (issue,author)).fetchone():return qualified(con,c,state)
            require(state.get('stage')=='blocked' and state.get('category')=='bundle_task_failed')
        task=workflow.Effects(b).plans.task(state['observed_task'],c['cto'])
        with b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (task['id'],)).fetchall();require(len(rows)==1);binding=dict(rows[0])
            require(binding['status']=='closed' and task.get('status')=='failed' and binding['agent_id']==c['cto']
                and task.get('agent_id')==c['cto'] and task.get('issue_id')==issue and binding['issue_id']==issue)
            tools=con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',
                (binding['request_id'],)).fetchone()[0];require(type(tools) is int and tools==0)
        expected={n:hashlib.sha256(Path(importlib.util.find_spec(n).origin).read_bytes()).hexdigest() for n in SOURCES}
        proxy=provider.proxy_info(b)
        entry=b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,AttachStderr=False,Tty=True,
            Cmd=['python','-c',PROXY_PROBE,binding['request_id'],digest(c)]))
        conn=b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),
                {'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(32769)
            require(response.status==200 and len(raw)<=32768)
        finally:conn.close()
        outcome=b.docker('GET','/exec/'+entry['Id']+'/json')
        require(outcome and not outcome.get('Running') and outcome.get('ExitCode')==0)
        value=json.loads(raw)
        require(set(value)=={'rejections','sources','passed'} and value['passed'] is True
            and value['sources']==expected and isinstance(value['rejections'],list) and len(value['rejections'])==1)
        require(provider.proxy_info(b)['Id']==proxy['Id'] and not maintenance.native_active(b))
        proof=dict(operation='calibration_read_qualification_v1',passed=True,source_sha256=digest(c),
            sources=expected,proxy_image=proxy['Image'],delivery_approval=False)
        # Reconcile a stale legacy projection through the normal source-bound
        # bridge, not by manufacturing the parent state required by transition.
        try:import generic_calibration_red_bridge as bridge
        except ImportError:from broker import generic_calibration_red_bridge as bridge
        with b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            parent=handoffs.load(con,author)
        original=workflow.Effects(b).plans.task(author,route['author'])
        require(bridge.reconcile_existing(b,route,original,parent))
        with b.db() as con:
            maintenance.transaction(con);require(maintenance.current(con)==barrier)
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            return transition(con,c,state,task,binding,tools,value['rejections'][0],proof,barrier,b.PREFIX)
