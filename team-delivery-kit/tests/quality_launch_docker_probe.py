"""Existing-controller subprocess: real Docker/ACP, synthetic native authority.

Never starts the candidate HTTP server, touches its installed DB, sends a prompt
or calls a model. All state lives beside this copied script in a private temp dir.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import uuid
import traceback
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),'/']
config=json.loads((ROOT/'input.json').read_text())
for name,expected in config['source_sha256'].items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
        raise ValueError('qualification source hash mismatch')
import candidate_broker as b
import native
import controller_maintenance as maintenance
import quality_lifecycle_enrollment as enrollment
import quality_author_launch as launch
import quality_author_admission as author_admission
import quality_progress as progress
import quality_test_review as review
import quality_review_reads as read_verifier
import quality_test_revision as revision
import quality_review_attestation as attestation
import acp_startup

b.STATE=ROOT/'state';b.STATE.mkdir(mode=0o700)
b.PREFIX=config['namespace'];b.OWNER=config['owner'];b.QUALITY_V2_ENABLED=True
# The installed process may have active v2 flags. This subprocess exercises
# the isolated author/Red/review adapter, not the installed team coordinator.
b.QUALITY_TEAM_ENABLED=False;b.QUALITY_EXCLUSIVE_ENABLED=False
b.QUALITY_IMPLEMENTATION_ENABLED=False;b.QUALITY_REVIEW_ENABLED=bool(config.get('review_chain'))
b.MODEL_NETWORK=b.PREFIX+'_model'
for key in ('QUALITY_WORKER_IMAGE','QUALITY_PREP_IMAGE','QUALITY_RED_IMAGE','QUALITY_COPY_IMAGE'):
    setattr(b,key,config[key])
b.IMAGE=b.QUALITY_WORKER_IMAGE
settings=config['settings'];(b.STATE/'native.json').write_text(json.dumps(settings))
if config.get('review_chain'):
    b.QUALITY_REVIEW_ENABLED=True
    for key in ('QUALITY_REVIEW_WORKER_IMAGE','QUALITY_TECHLEAD','QUALITY_CTO'):
        setattr(b,key,config[key])
os.chmod(b.STATE/'native.json',0o600)
task=dict(id=config['task_id'],agent_id=config['plan']['author'],issue_id=config['plan']['issue_id'],status='running',
    workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],created_at='2026-10-22T00:00:00Z')
issue=dict(id=task['issue_id'],workspace_id=settings['workspace_id'],title='Synthetic tests-only transport qualification',
    description='A01: test app.VALUE equals 1, preserving the old baseline. This is fixture data, not a product delivery.')
runs=[]
records={task['id']:task}
phase='database'
actual_native_task_record=native.task_record


def fixture_task_record(settings,ident,agent):
    # Fake only HTTP authority, not the adapter's parsing/ownership checks.
    rows=[dict(r) for r in records.values() if r['agent_id']==agent]
    with patch.object(native.urllib.request,'urlopen',side_effect=lambda *a,**k:io.StringIO(json.dumps(rows))):
        return actual_native_task_record(settings,ident,agent)


def save(name,value):
    with os.fdopen(os.open(b.STATE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as out:
        json.dump(value,out,sort_keys=True);out.flush();os.fsync(out.fileno())


def fixed_canary(grant,mode,path):
    """Operator fixture code through real handlers, explicitly not model work."""
    from acp_transport import worker_env
    config=(author_admission.tool_config(b.handoff_context(),grant['request_id']) if mode=='implementation'
        else review.tool_config(b.handoff_context(),grant['request_id']))
    argv=['docker','exec','--user','10000:10000']
    for env in worker_env(mode,False,execution_id=grant['request_id'],quality_phase_config=config):
        argv+=['--env',env]
    argv+=[b.PREFIX+'-job-'+grant['request_id'],'python',path]
    key='author' if mode=='implementation' else 'review'
    save(key+'-fixed-canary-intent.json',dict(argv=argv,synthetic_operator_fixture=True,model_calls=0))
    result=subprocess.run(argv,capture_output=True,text=True,timeout=45)
    save(key+'-fixed-canary-result.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    if result.returncode:raise ValueError('fixed canary failed; preserve original execution')
    receipt=json.loads(result.stdout)
    if receipt.get('status')!='passed' or receipt.get('model_calls')!=0 or receipt.get('delivery_approval') is not False:
        raise ValueError('actual fixed handler evidence required')
    return receipt


def review_launch(grant):
    fixed_canary(grant,'implementation','/quality_phase_registry_canary.py')
    name=b.PREFIX+'-job-'+grant['request_id']
    info=b.docker('GET','/containers/'+name+'/json')
    save('author-worker-before-stop.json',{k:info[k] for k in ('Id','Name','Image','State','Mounts')})
    b.SESSIONS[grant['request_id']].close();b.SESSIONS.clear()
    save('author-stop-intent.json',dict(container_id=info['Id']))
    stopped=subprocess.run(['docker','stop','--time','10',info['Id']],capture_output=True,text=True,timeout=30)
    save('author-stop-result.json',dict(exit_code=stopped.returncode,stdout=stopped.stdout,stderr=stopped.stderr))
    actual=b.docker('GET','/containers/'+info['Id']+'/json')
    if stopped.returncode or actual['State']['Running'] or actual['State']['Status']!='exited':
        raise ValueError('observe original author stop; never repeat it')
    # Only the synthetic native/task authority changes here, not capture proof.
    # Red and snapshots below must be generated by actual fixed Docker jobs.
    with b.db() as con:
        con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(grant['request_id'],))
    task['status']='completed'
    save('fixture-author-completion.json',dict(task_id=task['id'],native_api='synthetic_fixture',
        actual_worker_stopped=True,model_execution=False))
    deadline=time.monotonic()+60
    while True:
        progress.tick(b.handoff_context())
        observed=progress.load(b.handoff_context(),task['id'])
        if observed and observed[1]['stage']=='review_ready':break
        if observed and observed[1]['stage']=='technical_blocked':raise ValueError('actual Red chain rejected')
        if time.monotonic()>=deadline:raise ValueError('observe original Red chain; no restart')
        time.sleep(.25)
    context,_=review.prepare(b.handoff_context(),task['id'])
    def wake(*args,**kwargs):
        return dict(id=config['review_wakeup'],issue_id=task['issue_id'],agent_id=config['plan']['reviewer'])
    with patch.object(native,'ensure_review_start',side_effect=wake):
        dispatched=review.dispatch(b.handoff_context(),task['id'])
    reviewed=dict(id=config['review_task'],agent_id=config['plan']['reviewer'],issue_id=task['issue_id'],status='running',
        workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],wakeup_id=dispatched['wakeup_id'],
        handoff_note='DELIVERY_REVIEW_START '+context['marker']+'\nSource: '+task['id']+'\n'+context['instruction'],
        created_at='2026-10-22T01:00:00Z')
    expected_note=reviewed['handoff_note']
    reviewed['handoff_note']=('Wakeup '+reviewed['wakeup_id']+' triggered. Instruction:\n'+expected_note+
        '\nTrigger facts (read current state before deciding what to do):\ntime.due '+
        '{"kind":"at","planned_at":"2026-10-22T00:59:59Z"}\n')
    records[reviewed['id']]=reviewed;runs.append(reviewed)
    decoded=native.task_record(settings,reviewed['id'],reviewed['agent_id'])
    if decoded.get('scope_note_envelope_verified') is not True or decoded['handoff_note']!=expected_note:
        raise ValueError('actual strict native envelope decoding required')
    admitted=b.native_grant(dict(task_id=reviewed['id'],agent_id=reviewed['agent_id']))
    save('review-admission.json',dict(request_id=admitted['request_id'],task_id=reviewed['id'],capability_not_archived=True))
    startup=acp_startup.request(b.handoff_context(),admitted['capability'],{},begin=True)
    deadline=time.monotonic()+100
    while startup['startup_status']=='pending' and time.monotonic()<deadline:
        time.sleep(.25)
        startup=acp_startup.request(b.handoff_context(),admitted['capability'],{},begin=False)
    save('review-startup.json',startup)
    if startup['startup_status']!='ready':raise ValueError('readonly review startup did not become ready')
    receipts=[]
    for index,method in enumerate(('initialize','session/new')):
        response=b.session_operation(admitted['capability'],dict(frame=dict(jsonrpc='2.0',id=index+1,method=method,params={})))
        if 'error' in response or 'result' not in response:raise ValueError('actual review ACP request rejected')
        receipts.append(dict(method=method,status='passed',response_sha256=hashlib.sha256(json.dumps(response,sort_keys=True).encode()).hexdigest()))
    read_canary=fixed_canary(admitted,'review','/quality_review_registry_canary.py')
    with b.db() as con:
        capture=json.loads(con.execute('SELECT context FROM quality_red_captures WHERE task_id=?',(task['id'],)).fetchone()[0])
    prepared=capture['copy']['prepared']
    byte_reads=read_verifier.observe(prepared['file_inventory'],context['packet']['manifest_sha256'],
        context['read_paths'],read_canary['read_pairs'])
    save('operator-read-byte-binding.json',dict(reads=byte_reads,
        origin='fixed_operator_canary_not_native_stream',tests_approved=False,delivery_approval=False))
    b.SESSIONS[admitted['request_id']].close();b.SESSIONS.clear()
    state=review.load(b.handoff_context(),task['id'])[1]
    if state['tests_approved'] is not False:raise ValueError('launch cannot approve tests')
    correction=test_revision_launch(admitted,reviewed,context)
    return dict(status='passed',source_task=task['id'],task_id=reviewed['id'],request_id=admitted['request_id'],
        strict_native_envelope=True,native_envelope_sha256=decoded['scope_note_envelope_sha256'],
        manifest_sha256=context['packet']['manifest_sha256'],snapshot_mount='readonly',frames=receipts,
        handler_byte_binding=True,test_revision=correction,tests_approved=False,delivery_approval=False)


def test_revision_launch(review_grant,reviewed,context):
    """Synthetic rejection authority; actual seed/lock/handler/ACP operations.

    No model reviewed this fixture. Do not export its authority to native state.
    The preceding real snapshot/Red is reused; no installed DB is accessible.
    """
    worker=b.docker('GET','/containers/'+b.PREFIX+'-job-'+review_grant['request_id']+'/json')
    stop=subprocess.run(['docker','stop','--time','10',worker['Id']],capture_output=True,text=True,timeout=30)
    save('revision-review-stop.json',dict(container_id=worker['Id'],exit_code=stop.returncode,stdout=stop.stdout,stderr=stop.stderr))
    if stop.returncode or b.docker('GET','/containers/'+worker['Id']+'/json')['State']['Running']:
        raise ValueError('observe original review stop, never repeat')
    reviewed['status']='completed'
    packet=context['packet'];decision=dict(action='request_changes',reason='Synthetic correction transport fixture only.',
        manifest_sha256=packet['manifest_sha256'],plan_sha256=packet['plan_sha256'],red_sha256=packet['red_sha256'],
        criteria=['A01'],findings=[dict(criterion='A01',path='tests/test_new.py',test='__module__',line=1,
            quote='import unittest',expected='Synthetic fixture',observed='Operator fixture, not native review')])
    receipt=dict(operation='immutable_test_review_attestation_v2',source_task=task['id'],review_task=reviewed['id'],
        request_id=review_grant['request_id'],stage='changes_requested',owner=task['agent_id'],plan=packet['plan'],red=packet['red'],
        manifest_sha256=packet['manifest_sha256'],red_sha256=packet['red_sha256'],verdict=decision,
        tests_approved=False,execution_authorized=False,delivery_approval=False)
    observed=dict(namespace=b.PREFIX,source_task=task['id'])
    with b.db() as con:
        con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(review_grant['request_id'],))
        attestation.initialize(con)
        con.execute('INSERT INTO quality_review_attestations VALUES(?,?,?,?,?,?)',
            (task['id'],review_grant['request_id'],json.dumps(observed),json.dumps(receipt),review.quality.digest(observed),review.quality.digest(receipt)))
    # Only the reviewer authority is a fixture. Admission, lineage, real frozen
    # volume identity, actual helper jobs and handlers are not replaced.
    with patch.object(attestation,'collect',return_value=receipt):
        correction,_=revision.register(b.handoff_context(),task['id'])
    wake_id=str(uuid.uuid5(uuid.UUID(config['operation']),'revision_wakeup'))
    with patch.object(native,'ensure_scope_author_start',return_value=dict(id=wake_id,issue_id=task['issue_id'],agent_id=task['agent_id'])):
        revision.dispatch(b.handoff_context(),task['id'])
    corrected=dict(id=str(uuid.uuid5(uuid.UUID(config['operation']),'revision_task')),agent_id=task['agent_id'],
        issue_id=task['issue_id'],status='running',workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],
        wakeup_id=wake_id,handoff_note=revision.note(correction),created_at='2026-10-22T02:00:00Z')
    corrected['handoff_note']=('Wakeup '+wake_id+' triggered. Instruction:\n'+corrected['handoff_note']+
        '\nTrigger facts (read current state before deciding what to do):\ntime.due '+
        '{"kind":"at","planned_at":"2026-10-22T01:59:59Z"}\n')
    records[corrected['id']]=corrected;runs.append(corrected)
    admitted=b.native_grant(dict(task_id=corrected['id'],agent_id=corrected['agent_id']))
    startup=acp_startup.request(b.handoff_context(),admitted['capability'],{},begin=True);deadline=time.monotonic()+100
    while startup['startup_status']=='pending' and time.monotonic()<deadline:
        time.sleep(.25);startup=acp_startup.request(b.handoff_context(),admitted['capability'],{},begin=False)
    save('revision-startup.json',startup)
    if startup['startup_status']!='ready':raise ValueError('observe original revision startup, no replay')
    frames=[]
    for index,method in enumerate(('initialize','session/new')):
        response=b.session_operation(admitted['capability'],dict(frame=dict(jsonrpc='2.0',id=index+1,method=method,params={})))
        if 'error' in response or 'result' not in response:raise ValueError('actual revision ACP rejected')
        frames.append(dict(method=method,status='passed',response_sha256=hashlib.sha256(json.dumps(response,sort_keys=True).encode()).hexdigest()))
    from acp_transport import worker_env
    selection=author_admission.tool_config(b.handoff_context(),admitted['request_id'])
    argv=['docker','exec','--user','10000:10000']
    for env in worker_env('implementation',False,execution_id=admitted['request_id'],quality_phase_config=selection):
        argv+=['--env',env]
    expected=correction['seed']['test_sha256']['tests/test_new.py']
    argv+=['--env','QUALITY_REVISION_EXPECTED_SHA256='+expected,b.PREFIX+'-job-'+admitted['request_id'],
        'python','-c',(ROOT/'quality_revision_registry_canary.py').read_text()]
    probed=subprocess.run(argv,capture_output=True,text=True,timeout=45)
    save('revision-handler-probe.json',dict(exit_code=probed.returncode,stdout=probed.stdout,stderr=probed.stderr))
    if probed.returncode:raise ValueError('actual revision registry probe failed')
    result=json.loads(probed.stdout)
    if result['status']!='passed' or result['seed_sha256']!=expected or result['corrected_sha256']==expected or result['protected_unchanged'] is not True:
        raise ValueError('actual correction bytes/permissions required')
    b.SESSIONS[admitted['request_id']].close();b.SESSIONS.clear()
    return dict(status='passed',native_authority='synthetic_rejection_fixture',frames=frames,
        seed_unchanged=True,protected_unchanged=True,tests_approved=False,delivery_approval=False)


try:
    with b.db() as con:
        con.execute('CREATE TABLE grants(digest TEXT PRIMARY KEY,task_id TEXT,attempt INTEGER,mode TEXT,request_id TEXT,deadline REAL,used INTEGER,UNIQUE(task_id,attempt))')
        con.execute('CREATE TABLE native_bindings(request_id TEXT PRIMARY KEY,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
        con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
        con.execute('CREATE TABLE issue_bases(issue_id TEXT PRIMARY KEY,base_sha TEXT,volume TEXT,manifest_sha256 TEXT)')
        con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
        con.execute('CREATE TABLE acp_sessions(scope TEXT,session_id TEXT,PRIMARY KEY(scope,session_id))')
        con.execute('CREATE TABLE acp_events(request_id TEXT,method TEXT,session_id TEXT,success INTEGER)')
        con.execute('CREATE TABLE tool_events(request_id TEXT,prompt_id TEXT,tool_count INTEGER,PRIMARY KEY(request_id,prompt_id))')
        maintenance.initialize(con)
        state=dict(operation_id=config['operation'],namespace=b.PREFIX,stage='sealed',drained=True)
        con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(config['operation'],'sealed',json.dumps(state)))
    b.register_issue_base(config['base'])
    with patch.object(native,'issue_record',return_value=issue),\
            patch.object(native,'issue_task_runs',side_effect=lambda *_:list(runs)),\
            patch.object(native,'task_record',side_effect=fixture_task_record),\
            patch.object(maintenance,'native_active',return_value=[]):
        phase='enrollment'
        enrolled=enrollment.enroll(b.handoff_context(),dict(plan=config['plan'],contract=config['contract'],maintenance_operation=config['operation']))
        save('enrollment.json',enrolled)
        with b.db() as con:con.execute('DELETE FROM controller_maintenance')
        runs.append(task)
        phase='native_admission'
        grant=b.native_grant(dict(task_id=task['id'],agent_id=task['agent_id']))
        save('admission.json',dict(request_id=grant['request_id'],task_id=task['id'],capability_not_archived=True))
        phase='asynchronous_startup'
        startup=acp_startup.request(b.handoff_context(),grant['capability'],{},begin=True)
        deadline=time.monotonic()+100
        while startup['startup_status']=='pending' and time.monotonic()<deadline:
            time.sleep(.25)
            startup=acp_startup.request(b.handoff_context(),grant['capability'],{},begin=False)
        save('startup.json',startup)
        if startup['startup_status']!='ready':raise ValueError('real startup did not become ready; inspect original journal')
        frames=[dict(jsonrpc='2.0',id=1,method='initialize',params={}),
            dict(jsonrpc='2.0',id=2,method='session/new',params={})]
        receipts=[]
        for frame in frames:
            phase=frame['method']
            response=b.session_operation(grant['capability'],dict(frame=frame))
            if 'error' in response or 'result' not in response:raise ValueError('real ACP request rejected')
            if frame['method']=='initialize' and response['result'].get('protocolVersion')!=1:
                raise ValueError('actual ACP protocol mismatch')
            if frame['method']=='session/new' and not response['result'].get('sessionId'):
                raise ValueError('actual ACP session absent')
            receipts.append(dict(method=frame['method'],status='passed',response_sha256=hashlib.sha256(json.dumps(response,sort_keys=True).encode()).hexdigest()))
        phase='readonly_review_launch' if config.get('review_chain') else 'transport_close'
        reviewed=review_launch(grant) if config.get('review_chain') else None
        if not reviewed:
            b.SESSIONS[grant['request_id']].close()
            b.SESSIONS.clear()
        result=dict(operation='quality_native_launch_docker_acp_fixture_v2',status='passed',
            native_api='synthetic_fixture',docker='real',acp='real',frames=receipts,
            request_id=grant['request_id'],task_id=task['id'],model_calls=0,prompts_sent=0,
            installed_controller_unchanged=True,native_delivery_qualification=False,delivery_approval=False)
        if reviewed:result['review_launch']=reviewed
        save('run-result.json',result);print(json.dumps(result),flush=True)
except Exception as error:
    result=dict(operation='quality_native_launch_docker_acp_fixture_v2',status='failed',phase=phase,
        error_class=type(error).__name__,error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),
        native_api='synthetic_fixture',model_calls=0,prompts_sent=0,delivery_approval=False)
    save('failure-location.json',dict(frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name)
        for f in traceback.extract_tb(error.__traceback__)]))
    save('run-result.json',result);print(json.dumps(result),flush=True)
    raise SystemExit(1)
