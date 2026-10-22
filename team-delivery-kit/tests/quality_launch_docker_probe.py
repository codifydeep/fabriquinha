"""Existing-controller subprocess: real Docker/ACP, synthetic native authority.

Never starts the candidate HTTP server, touches its installed DB, sends a prompt
or calls a model. All state lives beside this copied script in a private temp dir.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
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
import acp_startup

b.STATE=ROOT/'state';b.STATE.mkdir(mode=0o700)
b.PREFIX=config['namespace'];b.OWNER=config['owner'];b.QUALITY_V2_ENABLED=True
b.MODEL_NETWORK=b.PREFIX+'_model'
for key in ('QUALITY_WORKER_IMAGE','QUALITY_PREP_IMAGE','QUALITY_RED_IMAGE','QUALITY_COPY_IMAGE'):
    setattr(b,key,config[key])
b.IMAGE=b.QUALITY_WORKER_IMAGE
settings=config['settings'];(b.STATE/'native.json').write_text(json.dumps(settings))
os.chmod(b.STATE/'native.json',0o600)
task=dict(id=config['task_id'],agent_id=config['plan']['author'],issue_id=config['plan']['issue_id'],status='running',
    workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],created_at='2026-10-22T00:00:00Z')
issue=dict(id=task['issue_id'],workspace_id=settings['workspace_id'],title='Synthetic tests-only transport qualification',
    description='A01: test app.VALUE equals 1, preserving the old baseline. This is fixture data, not a product delivery.')
runs=[]
phase='database'


def save(name,value):
    with os.fdopen(os.open(b.STATE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as out:
        json.dump(value,out,sort_keys=True);out.flush();os.fsync(out.fileno())


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
            patch.object(native,'task_record',side_effect=lambda *_:dict(task)),\
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
        phase='transport_close'
        b.SESSIONS[grant['request_id']].close()
        b.SESSIONS.clear()
        result=dict(operation='quality_native_launch_docker_acp_fixture_v2',status='passed',
            native_api='synthetic_fixture',docker='real',acp='real',frames=receipts,
            request_id=grant['request_id'],task_id=task['id'],model_calls=0,prompts_sent=0,
            installed_controller_unchanged=True,native_delivery_qualification=False,delivery_approval=False)
        save('run-result.json',result);print(json.dumps(result),flush=True)
except Exception as error:
    result=dict(operation='quality_native_launch_docker_acp_fixture_v2',status='failed',phase=phase,
        error_class=type(error).__name__,error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),
        native_api='synthetic_fixture',model_calls=0,prompts_sent=0,delivery_approval=False)
    save('run-result.json',result);print(json.dumps(result),flush=True)
    raise SystemExit(1)
