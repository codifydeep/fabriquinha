"""Controller-only sanitized diagnostics from the exact owned proxy/execution."""
import json
import uuid
from artifact_rejection_receipts import from_event

def durable_receipts(b,proxy,execution):
    script=('import sys,json,model_proxy,artifact_rejection_receipts as r;'
            'print(json.dumps(r.read(model_proxy.COUNTER_PATH,sys.argv[1])))')
    record=b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,
        AttachStderr=False,Tty=True,Env=['PYTHONPATH=/'],Cmd=['python','-c',script,execution]))
    conn=b.DockerConnection('localhost',timeout=10)
    try:
        conn.request('POST','/v1.45/exec/'+record['Id']+'/start',
            json.dumps(dict(Detach=False,Tty=True)),{'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(16385)
        if response.status!=200 or len(raw)>16384:raise ValueError('bounded receipt query unavailable')
    finally:conn.close()
    outcome=b.docker('GET','/exec/'+record['Id']+'/json')
    if outcome['Running'] or outcome['ExitCode']!=0:return []  # old proxy migration
    receipts=json.loads(raw)
    for receipt in receipts:
        canonical=from_event(dict(event='model_proxy_request',status=502,
            artifact_selected_tool=receipt.get('tool'),artifact_contract_present=True,
            artifact_rejection_category=receipt.get('category'),execution_id=execution,
            artifact_rejection_diagnostic=receipt.get('structure'),
            call_number=receipt.get('call_number')))
        if canonical!=receipt:raise ValueError('invalid persisted rejection')
    return receipts

def decode_logs(raw):
    chunks=[];i=0
    while i+8<=len(raw):
        size=int.from_bytes(raw[i+4:i+8],'big');i+=8
        if size>len(raw)-i:raise ValueError('truncated proxy log frame')
        chunks.append(raw[i:i+size]);i+=size
    if i!=len(raw):raise ValueError('invalid proxy log frame')
    return b''.join(chunks).decode().splitlines()

def fetch(b,issue,task):
    for identity in (issue,task):
        if str(uuid.UUID(identity))!=identity:raise ValueError('canonical diagnostic identity required')
    path=b.STATE/'artifact-rejections'/(task+'.json')
    if path.exists() or path.is_symlink():
        if path.is_symlink():raise ValueError('unsafe diagnostic')
        result=json.loads(path.read_text())
        if result['issue_id']!=issue or result['task_id']!=task:raise ValueError('diagnostic identity drift')
        return result
    with b.db() as c:
        rows=c.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.issue_id=?',(task,issue)).fetchall()
        if len(rows)!=1 or rows[0]['status'] not in ('failed','closed'):return None
        execution=rows[0]['request_id']
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical execution required')
    proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
    labels=(proxy or {}).get('Config',{}).get('Labels',{})
    if (not proxy or not proxy['State']['Running'] or labels.get('com.docker.compose.project')!=b.PREFIX
            or labels.get('com.docker.compose.service')!='model-proxy'):raise ValueError('owned proxy required')
    receipts=durable_receipts(b,proxy,execution)
    provenance='owned_proxy_durable_validator_receipt'
    # Recent bounded Docker logs also support migration of an actual pre-upgrade
    # rejection. Never accept a worker message as validator evidence.
    if not receipts:
        provenance='owned_proxy_validator_log'
        conn=b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('GET','/v1.45/containers/'+proxy['Id']+'/logs?stdout=1&tail=128')
            response=conn.getresponse();raw=response.read(262145)
            if response.status!=200 or len(raw)>262144:raise ValueError('bounded proxy evidence unavailable')
        finally:conn.close()
        for line in decode_logs(raw):
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('execution_id')==execution:
                receipt=from_event(event)
                if receipt:receipts.append(receipt)
    if len(receipts)!=1:return None
    result=dict(kind='rejected_forced_tool_response' if receipts[0]['operation']=='rejected_forced_tool_response_v1'
        else 'rejected_test_write',issue_id=issue,task_id=task,
        provenance=provenance,proxy_image=proxy['Image'],**receipts[0])
    path.parent.mkdir(mode=0o700,exist_ok=True)
    if path.parent.is_symlink():raise ValueError('unsafe evidence directory')
    with path.open('x') as out:json.dump(result,out,sort_keys=True)
    path.chmod(0o600)
    return result
