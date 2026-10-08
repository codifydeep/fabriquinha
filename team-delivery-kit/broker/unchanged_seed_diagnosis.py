"""Fresh read-only evidence for a failed seeded R1, not a recovered proxy log.

One fixed offline job verifies the ENTIRE frozen candidate against the approved
seed. It can reopen independent diagnosis, never approve Red or repeat an author.
"""
import hashlib
import json
import time
from types import SimpleNamespace

IMAGE='sha256:3cd0a9b7b96878f81e80463147d78ee69c7c94236bf01c4de43e38a18b083bd1'
SCRIPT=('import json,os;from r3_snapshot_probe import probe;'
        'print(json.dumps(probe("/delivery",os.environ["EXPECTED_SEED_MANIFEST"]),sort_keys=True))')


def read_only_messages(messages):
    uses=[m for m in messages if m.get('type')=='tool_use']
    results=[m for m in messages if m.get('type')=='tool_result']
    ids=[m.get('call_id') for m in uses]
    if (not uses or len(uses)!=len(results) or len(uses)>256
            or any(m.get('tool')!='read_file' for m in uses+results)
            or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids)
            or {m.get('call_id') for m in results}!=set(ids)
            or any(m.get('output_truncated') for m in results)):
        raise ValueError('only complete paired actual read tools required')
    return len(uses)


def validate_result(value,expected):
    if (set(value)!={'status','observation','manifest_sha256','file_count','total_bytes'}
            or value['status']!='passed' or value['observation']!='snapshot_hashes_match'
            or value['manifest_sha256']!=expected or type(value['file_count']) is not int
            or not 1<=value['file_count']<=2048 or type(value['total_bytes']) is not int
            or not 0<value['total_bytes']<=134217728):
        raise ValueError('entire unchanged seed inventory proof required')


def payload(b,source,volume,manifest):
    try:import harness_qualification as jobs
    except ImportError:from broker import harness_qualification as jobs
    env=dict(e.split('=',1) for e in jobs.image_environment(SimpleNamespace(IMAGE=IMAGE,docker=b.docker)))
    env.update(PYTHONPATH='/',EXPECTED_SEED_MANIFEST=manifest)
    return dict(Image=IMAGE,User='10000:10000',Entrypoint=['python'],Cmd=['-c',SCRIPT],
        Env=[k+'='+v for k,v in sorted(env.items())],NetworkDisabled=True,
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':source,'delivery-kit.purpose':'unchanged-seed-diagnosis'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=64,
            Mounts=[dict(Type='volume',Source=volume,Target='/delivery',ReadOnly=True)],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'}))


def capture(b,issue,source):
    try:import native,remediation_runtime_guard as guard,harness_qualification as jobs
    except ImportError:from broker import native,remediation_runtime_guard as guard,harness_qualification as jobs
    with b.db() as con:
        row=con.execute('SELECT stage,data FROM delivery_handoffs WHERE source_task=? AND issue_id=?',(source,issue)).fetchone()
        if not row:return None
        data=json.loads(row['data'])
        if (row['stage']!='test_first_blocked' or data.get('error')!='test_first_cto_requires_replanning'
                or data.get('diagnostic') or data.get('decision',{}).get('action')!='escalate_cto'
                or not data.get('cto_task') or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):return None
        bindings=con.execute('SELECT n.agent_id,n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) '
            'WHERE n.task_id=? AND n.issue_id=?',(source,issue)).fetchall()
        frozen=con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
        if len(bindings)!=1 or bindings[0]['status']!='closed' or not frozen or frozen['status']!='complete':return None
        volume=frozen['volume'];agent=bindings[0]['agent_id']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
    value=guard.qualified(b,issue)
    if not value or not value.get('amendment') or value['steps'][0]['owner']!=agent:return None
    settings=json.loads((b.STATE/'native.json').read_text())
    runs=native.issue_task_runs(settings,issue);authors=[r for r in runs if r.get('agent_id')==agent]
    if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
            or any(r.get('status') in ('queued','dispatched','running') for r in runs)):return None
    task=native.task_record(settings,source,agent)
    cto=native.task_record(settings,data['cto_task'],route['cto'])
    if (task.get('status')!='failed' or task.get('issue_id')!=issue
            or task.get('failure_reason')!='agent_error.provider_server_error'
            or route['cto']==agent or cto.get('agent_id')!=route['cto']
            or cto.get('status')!='completed' or cto.get('issue_id')!=issue
            or cto.get('wakeup_id')!=data.get('test_first_cto_wakeup')):return None
    count=read_only_messages(native.task_messages(settings,source))
    vol=b.docker('GET','/volumes/'+volume)
    if (vol.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
            or vol.get('Labels',{}).get('delivery-kit.source-task')!=source):
        raise ValueError('controller-owned immutable failed snapshot required')
    manifest=value['previous_new_test_delivery']['manifest_sha256'];expected=payload(b,source,volume,manifest)
    name=b.PREFIX+'-unchanged-seed-'+source
    identity=dict(issue_id=issue,source_task=source,request_id=bindings[0]['request_id'],read_tools=count,
        snapshot_volume=volume,seed_manifest_sha256=manifest,payload=expected)
    with b.LOCK,b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS unchanged_seed_diagnoses(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        row=con.execute('SELECT identity,state FROM unchanged_seed_diagnoses WHERE source_task=?',(source,)).fetchone()
        create=not row
        if row:
            old,state=map(json.loads,row)
            if old!=identity:raise ValueError('unchanged seed diagnostic identity drift')
        else:
            state=dict(stage='create_intent',at=time.time())
            con.execute('INSERT INTO unchanged_seed_diagnoses VALUES(?,?,?)',(source,json.dumps(identity,sort_keys=True),json.dumps(state)))
    def save(new):
        with b.db() as con:con.execute('UPDATE unchanged_seed_diagnoses SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new
    if state['stage']=='blocked':return None
    info=b.docker('GET','/containers/'+name+'/json')
    if state['stage']=='create_intent':
        if not info and create:
            b.docker('POST','/containers/create?name='+name,expected);info=b.docker('GET','/containers/'+name+'/json')
        if not info:
            if time.time()-state['at']>=600:save({**state,'stage':'blocked','category':'creation_unobserved'})
            return None
        jobs.verify_job(info,expected)
        if info['State']['Status']!='created':raise ValueError('new job must await durable start intent')
        state=save({**state,'stage':'start_intent','container_id':info['Id']})
        b.docker('POST','/containers/'+info['Id']+'/start')
    if not info or info['Id']!=state.get('container_id'):raise ValueError('same durable diagnostic job required')
    jobs.verify_job(info,expected)
    if info['State']['Running'] or info['State']['Status']=='created':
        if time.time()-state['at']>=600:save({**state,'stage':'blocked','category':'execution_unobserved'})
        return None
    if info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
        save({**state,'stage':'blocked','category':'candidate_differs_from_seed'});return None
    raw=b.docker_stdout(info['Id'],include_stderr=False,limit=16384);proof=json.loads(raw);validate_result(proof,manifest)
    receipt=dict(kind='unchanged_seed_read_only_failure',operation='unchanged_seed_read_only_failure_v1',
        issue_id=issue,task_id=source,manifest_sha256=manifest,snapshot_volume=volume,
        read_tools=count,inventory=proof,output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        proxy_failure_cause_proven=False,write_executed=False,tests_executed=False,red_verified=False,delivery_approval=False)
    if state['stage']=='passed' and state.get('receipt')!=receipt:raise ValueError('retained diagnostic proof drift')
    save({**state,'stage':'passed','receipt':receipt});return receipt
