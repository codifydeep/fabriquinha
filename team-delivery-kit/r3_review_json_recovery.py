"""Once-only fresh review after proven malformed JSON and changed fixed transport."""
import hashlib
import json
from pathlib import Path
from portable_remediation_intake import digest,read
from release_eval import command,save_receipt
from r3_incident_transport import REPORT


def qualify(report):
    rows=report.get('failures',[])
    if report.get('active')!=0 or len(rows)!=1:raise ValueError('idle one failed review required')
    row=rows[0];receipt=row['receipt'];rejections=row['rejections']
    if receipt.get('method')!='session/prompt' or receipt.get('code')!=-32603 or receipt.get('approval') is not False or len(rejections)!=1:
        raise ValueError('closed failed review transport required')
    rejected=rejections[0];shape=rejected.get('response_shape',{})
    if (rejected.get('operation')!='rejected_typed_decision_adapter_v1'
            or rejected.get('category')!='typed_arguments_invalid'
            or rejected.get('delivery_approval') is not False or rejected.get('worker_tool_executed') is not False
            or shape.get('parsed') is not True or shape.get('terminal') is not True
            or shape.get('submissions')!=1 or shape.get('expected_tool') is not True
            or shape.get('arguments_json_valid') is not False or shape.get('content_shape')!='empty'):
        raise ValueError('exact malformed nonaccepted review required')


def recover(private,incoming,*,instance='delivery-kit-port2'):
    from r3_incident_runtime import Effects,validate_decision
    if (incoming.get('stage')!='blocked' or incoming.get('category')!='invalid_incident_submission'
            or incoming.get('review_transport_recovery_sha256') or not incoming.get('proposal')
            or not incoming.get('diagnosis_task')):return None
    root=Path(private);key=incoming['incident_sha256'];path=root/'r3-incidents'/(key+'.json')
    saved=read(path);state=saved['state'];config=saved['config']
    if state!={k:v for k,v in incoming.items() if k!='experiment'}:raise ValueError('exact persisted failed review required')
    fx=Effects(instance)
    selected=dict(state,stage='awaiting_review');task=fx.task(config,selected,state['task_id'])
    if task.get('status')!='failed' or task.get('failure_reason')!='agent_error.provider_server_error':return None
    author=dict(state,stage='awaiting_diagnose',task_id=state['diagnosis_task'],wakeup_id=state['diagnosis_wakeup'])
    proposal=validate_decision(config,author,fx.task(config,author,author['task_id']))
    if proposal!=state['proposal'] or digest(proposal)!=state['proposal_sha256']:
        raise ValueError('original independently authored proposal drift')
    report=json.loads(command('docker','exec','-w','/',instance+'-execution-broker-1','python','-c',REPORT,json.dumps([task['id']])))
    row=report['failures'][0]
    row['rejections']=json.loads(command('docker','exec','-w','/',instance+'-model-proxy-1','python','-c',
        'import json,sys,sqlite3;c=sqlite3.connect("file:/meter/deterministic-reads.sqlite?mode=ro",uri=True);'
        'print(json.dumps([json.loads(r[0]) for r in c.execute("SELECT receipt FROM typed_decision_rejections WHERE execution_id=?",(sys.argv[1],))]));c.close()',row['execution']))
    qualify(report)
    actual=command('docker','inspect','--format','{{.Image}}',instance+'-model-proxy-1')
    expected=command('docker','image','inspect','--format','{{.Id}}','delivery-kit-model-proxy:20261008.102')
    if actual!=expected:return None
    canary=json.loads(command('docker','exec','-w','/',instance+'-model-proxy-1','python','-c',
        'import json,sys;from r3_json_probe import run;print(json.dumps(run(sys.argv[1])))',task['handoff_note']))
    policy=hashlib.sha256(Path(__file__).with_name('typed_decision_contract.py').read_bytes()).hexdigest()
    probe=hashlib.sha256(Path(__file__).with_name('r3_json_probe.py').read_bytes()).hexdigest()
    if canary!=dict(status='r3_json_transport_qualified',policy_sha256=policy,probe_sha256=probe,execution_authorized=False,worker_tool_executed=False):
        raise ValueError('installed JSON feedback qualification drift')
    proof=dict(operation='qualified_r3_json_review_recovery_v1',issue_id=state['issue_id'],incident_sha256=key,
        proposal_sha256=state['proposal_sha256'],failed_task=task['id'],failed_wakeup=state['wakeup_id'],
        reviewer=task['agent_id'],proxy_image=actual,canary=canary,report=report,
        original_proposal_preserved=True,execution_authorized=False,release_homologated=False)
    recovery_sha=digest(proof)
    program='''import broker as b,json,sys
p=json.loads(sys.argv[1]);key=sys.argv[2]
with b.LOCK,b.db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS r3_json_review_recoveries(recovery_sha256 TEXT PRIMARY KEY,failed_task TEXT UNIQUE,proof TEXT)')
 old=c.execute('SELECT recovery_sha256,proof FROM r3_json_review_recoveries WHERE failed_task=?',(p['failed_task'],)).fetchone()
 if old:assert old[0]==key and json.loads(old[1])==p
 else:c.execute('INSERT INTO r3_json_review_recoveries VALUES(?,?,?)',(key,p['failed_task'],json.dumps(p,sort_keys=True)))
print(json.dumps(dict(registered=True,recovery_sha256=key)))
'''
    result=json.loads(command('docker','exec','-w','/',instance+'-execution-broker-1','python','-c',program,json.dumps(proof),recovery_sha))
    if result!=dict(registered=True,recovery_sha256=recovery_sha):raise ValueError('recovery registration uncertain; observe same intent')
    if read(path)!=saved:raise ValueError('incident changed before review recovery')
    revised={**state,'stage':'review_dispatch','previous_failed_review':state,
             'review_transport_recovery_sha256':recovery_sha,'review_transport_recovery':proof}
    for field in ('category','next_action','wakeup_id','task_id','dispatched_at','observation_started'):
        revised.pop(field,None)
    save_receipt(path,dict(config=config,state=revised))
    return revised
