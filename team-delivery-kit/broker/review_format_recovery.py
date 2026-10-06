"""Controller-only, once-per-issue fresh review after a changed format contract.

Never recovers a verdict, restarts an author, or replenishes bootstrap retries.
The original rejection and complete read provenance remain immutable evidence.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import time
try:
    import native, handoff_runtime, execution_diagnosis_recovery
except ImportError:
    from broker import native, handoff_runtime, execution_diagnosis_recovery


def qualify_proxy(b,image):
    """Fixed, network-free in-process canary; no provider call or worker tool."""
    proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
    labels=(proxy or {}).get('Config',{}).get('Labels',{})
    if (not proxy or proxy['Image']!=image or not proxy.get('State',{}).get('Running')
            or labels.get('com.docker.compose.project')!=b.PREFIX
            or labels.get('com.docker.compose.service')!='model-proxy'):
        raise ValueError('owned installed format proxy required')
    script='''import hashlib,json
from pathlib import Path
import typed_decision_contract as t
from decision_schema import apply
from structured_response_contract import StructuredResponseRejected
path='/evidence/candidate/tests/test_canary.py'
body=t.apply(apply({'messages':[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+'a'*64+'\\nDELIVERY_TYPED_REVIEW_V1:'+'a'*64+'\\nDELIVERY_TEST_FINDINGS_V1\\nDELIVERY_REVIEW_READ_PATH:'+path+'\\n'},
 {'role':'assistant','tool_calls':[{'id':'read','function':{'name':'read_file','arguments':json.dumps(dict(path=path))}}]},
 {'role':'tool','tool_call_id':'read','content':json.dumps(dict(content='1|assert value\\n',total_lines=1))}]}))
bad=dict(action='approve_test_revision',reason='x'*1300,optional_files=[],manifest_sha256='a'*64,findings=[])
def wire(d):return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'type':'function','function':{'name':t.REVIEW_NAME,'arguments':json.dumps(d)}}]}}]}).encode()
try:t.translate(body,wire(bad),'application/json')
except StructuredResponseRejected as e:
 assert e.category=='typed_schema_maxLength' and len(e.length_feedback)==2
 body['messages'].extend(e.length_feedback)
else:raise AssertionError('oversized decision accepted')
good={**bad,'reason':'Observed tests'}
t.translate(body,wire(good),'application/json')
try:t.translate(body,wire({**good,'action':'reject_test_revision','findings':[{}]}),'application/json')
except StructuredResponseRejected:pass
else:raise AssertionError('changed verdict accepted')
print(json.dumps(dict(source_sha256=hashlib.sha256(Path(t.__file__).read_bytes()).hexdigest(),canary=True,model_calls=0)))
'''
    created=b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,
        AttachStderr=False,Tty=True,Env=['PYTHONPATH=/'],Cmd=['python','-c',script]))
    conn=b.DockerConnection('localhost',timeout=10)
    try:
        conn.request('POST','/v1.45/exec/'+created['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),
                     {'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(2049)
        if response.status!=200 or len(raw)>2048:raise ValueError('bounded proxy canary unavailable')
    finally:conn.close()
    outcome=b.docker('GET','/exec/'+created['Id']+'/json')
    if outcome.get('Running') or outcome.get('ExitCode')!=0:raise ValueError('installed proxy canary failed')
    proof=json.loads(raw)
    if (proof.get('canary') is not True or proof.get('model_calls')!=0
            or proof.get('source_sha256')!=hashlib.sha256(Path('/typed_decision_contract.py').read_bytes()).hexdigest()):
        raise ValueError('installed proxy contract drift')
    return proof


def prepare(state, red, task, reviewer, rejection, reads, paths, proxy_image):
    failure=state.get('review_failure') or {}
    shape=rejection.get('response_shape') or {}
    if (state.get('format_recovery') or state.get('status')!='blocked'
            or state.get('review_task') or state.get('decision')
            or state.get('terminal_contract')!='typed-review-v1'
            or failure.get('task_id')!=task['id']
            or failure.get('detail')!='independent test review did not complete'
            or task.get('status')!='failed' or task.get('agent_id')!=reviewer
            or task.get('wakeup_id')!=state.get('wakeup_id')
            or state.get('source_task')!=red['task_id']
            or state.get('candidate_volume')!=red['volume']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or rejection.get('operation')!='rejected_typed_decision_adapter_v1'
            or rejection.get('category')!='typed_schema_maxLength'
            or rejection.get('delivery_approval') is not False
            or rejection.get('worker_tool_executed') is not False
            or not re.fullmatch(r'[a-f0-9]{64}',rejection.get('upstream_sha256',''))
            or not all(shape.get(k) is True for k in ('parsed','terminal','expected_tool','arguments_json_valid'))
            or shape.get('arguments_schema_valid') is not False or shape.get('submissions')!=1
            or not paths or not set(paths)<=set(reads)
            or any(type(reads[p].get('lines')) is not int or reads[p]['lines']<=0
                   or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',proxy_image)):
        raise ValueError('exact failed fully observed immutable format review required')
    updated=copy.deepcopy(state)
    updated['format_recovery']=dict(operation='readonly_review_format_recovery_v1',
        failed_task=task['id'],failed_wakeup=state['wakeup_id'],proxy_image=proxy_image,
        rejection=copy.deepcopy(rejection),read_evidence=copy.deepcopy(reads),
        prior_state=copy.deepcopy(state),attempt_limit=1,author_restarted=False,
        delivery_approval=False,at=time.time())
    for key in ('wakeup_id','marker','dispatched_at','reason','review_failure','read_evidence'):
        updated.pop(key,None)
    updated['status']='dispatch_intent'
    return updated


def register(b,payload):
    """Internal maintenance only: paused route, pinned installed proxy, closed leases."""
    if not isinstance(payload,dict) or set(payload)!={'issue_id','failed_task','manifest_sha256','proxy_image'}:
        raise ValueError('exact format recovery request required')
    with b.LOCK,b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle format recovery required')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        if route.get('enabled'):raise ValueError('paused route required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(payload['issue_id'],)).fetchone())
        if state.get('format_recovery'):
            receipt=state['format_recovery']
            if (receipt['failed_task']!=payload['failed_task'] or receipt['proxy_image']!=payload['proxy_image']
                    or state['manifest_sha256']!=payload['manifest_sha256']):
                raise ValueError('format recovery already consumed')
            return dict(status=state['status'],delivery_approval=False,model_calls_started=0)
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        if red['red']['manifest_sha256']!=payload['manifest_sha256']:raise ValueError('snapshot drift')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,payload['failed_task'],config['reviewer'])
        if task.get('issue_id')!=payload['issue_id']:raise ValueError('native issue drift')
        if any(r.get('status') in ('queued','dispatched','running') for r in native.issue_task_runs(settings,payload['issue_id'])):
            raise ValueError('idle native review required')
        binding=con.execute('SELECT request_id FROM native_bindings WHERE task_id=? AND agent_id=? AND issue_id=?',
            (task['id'],config['reviewer'],payload['issue_id'])).fetchall()
        if len(binding)!=1:raise ValueError('unique failed reviewer binding required')
        qualification=qualify_proxy(b,payload['proxy_image'])
        rejection=execution_diagnosis_recovery.format_rejection(b,binding[0][0],expected_image=payload['proxy_image'])
        reads=handoff_runtime.Effects(b,settings).read_evidence(task)
        paths=['/evidence/candidate/'+p for p in red['red']['test_sha256']]
        if not config.get('initial_review'):
            paths+=['/evidence/previous/'+p for p in config['old_red']['red']['test_sha256']]
        updated=prepare(state,red,task,config['reviewer'],rejection,reads,paths,payload['proxy_image'])
        updated['format_recovery']['qualification']=qualification
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',(json.dumps(updated,sort_keys=True),payload['issue_id']))
        return dict(status=updated['status'],delivery_approval=False,author_restarted=False,model_calls_started=0)
