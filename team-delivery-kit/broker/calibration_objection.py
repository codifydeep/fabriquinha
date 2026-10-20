"""Authenticate a technical objection; it never becomes a bundle or approval."""
import hashlib
import json
from calibration_response_contract import context,request
from generic_harness_calibration import digest,require
from structured_response_contract import _unique


def from_task(c,task,wakeup,execution,reads,*,required_paths=None):
    require(task.get('status')=='completed' and task.get('agent_id')==c['cto']
        and task.get('issue_id')==c['issue_id'] and task.get('wakeup_id')==wakeup
        and c['cto']!=c['reviewer'] and task['id']!=c['author_task'])
    raw=(task.get('result') or {}).get('output');require(isinstance(raw,str) and 1<=len(raw.encode())<=786432)
    value=json.loads(raw,object_pairs_hook=_unique)
    if not isinstance(value,dict) or value.get('action')!='calibration_objection':return None
    require(set(value)=={'action','reason','execution_authorized','delivery_approval'}
        and isinstance(value['reason'],str) and 1<=len(value['reason'])<=1200
        and value['execution_authorized'] is False and value['delivery_approval'] is False)
    baseline=sorted('/evidence/'+root+'/'+path for root in ('candidate','previous') for path in c['test_files'])
    paths=required_paths if required_paths is not None else baseline
    require(isinstance(paths,list) and paths==sorted(set(paths)) and set(paths)>=set(baseline))
    expected=context('bundle',paths,digest(c),engine=c.get('calibration_engine') if 'calibration_engine' in c else None)
    require(request(dict(messages=[dict(role='user',content=task.get('handoff_note',''))]))==expected)
    for path in paths:
        observed=reads.get(path,{})
        require(type(observed.get('lines')) is int and observed['lines']>0 and observed['lines']==observed.get('total_lines'))
    return dict(operation='calibration_technical_objection_v1',source_sha256=digest(c),
        producer_task=task['id'],actor=c['cto'],wakeup_id=wakeup,execution_id=execution,
        artifact_sha256=hashlib.sha256(raw.encode()).hexdigest(),reason=value['reason'],
        read_evidence={p:reads[p] for p in paths},candidate_manifest_sha256=c['prepared']['manifest_sha256'],
        author_retry_authorized=False,execution_authorized=False,delivery_approval=False)


def collect(b,c,task,wakeup):
    try:import generic_calibration_workflow as workflow
    except ImportError:from broker import generic_calibration_workflow as workflow
    fx=workflow.Effects(b);fx.verify(c)
    actual=fx.plans.task(task['id'],c['cto'])
    with b.db() as con:
        rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
            (actual['id'],)).fetchall();require(len(rows)==1);binding=dict(rows[0])
        require(binding['status']=='closed' and binding['agent_id']==c['cto'] and binding['issue_id']==c['issue_id']
            and binding['scope'].split(':')[-2:]==['planning',actual['id']])
    paths=None
    with b.db() as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='generic_calibration_workflows'").fetchone()
        row=con.execute('SELECT state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
            (c['issue_id'],c['author_task'])).fetchone() if exists else None
        state=json.loads(row[0]) if row else {}
        if state.get('dependency_read_recovery_id'):
            try:import calibration_read_recovery as recovery
            except ImportError:from broker import calibration_read_recovery as recovery
            receipt=recovery.qualified(con,c,state);paths=receipt['measurement']['required_paths']
    return from_task(c,actual,wakeup,binding['request_id'],fx.plans.reads(actual),required_paths=paths)
