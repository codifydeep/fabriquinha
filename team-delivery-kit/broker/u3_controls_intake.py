"""Evidence-bound CTO planning after approved harness maintenance, no author grant."""
import hashlib,json,time,uuid
try:import admission_controls_spike as admission,test_decomposition as plans, native,handoff_runtime
except ImportError:from broker import admission_controls_spike as admission,test_decomposition as plans,native,handoff_runtime


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def qualify(state,proof):
    validation=state['validation'];suite=state['suite_receipt'];review=state['maintenance_review_receipt']
    if (state.get('stage')!='maintenance_review_approved' or state.get('delivery_approval') is not False
            or suite.get('exit_code')!=0 or suite.get('tests')!=259
            or suite.get('source_task')!=state['author_task']
            or suite.get('test_sha256')!=validation['test_sha256']
            or suite.get('manifest_sha256')!=validation['manifest_sha256']
            or review.get('source_task')!=state['author_task'] or review.get('reviewer')==review.get('author')
            or review.get('manifest_sha256')!=validation['manifest_sha256']
            or review.get('decision',{}).get('action')!='approve_test_revision'):
        raise ValueError('actual passing maintenance and independent exact review required')
    if (proof.get('schema')!='u3-negative-controls-v1' or proof.get('inputs_unchanged') is not True
            or proof.get('delivery_approval') is not False or proof.get('valid_red_green_receipt') is not False
            or proof.get('network')!='none' or proof.get('model_calls')!=0
            or proof.get('controls_complete') is not False
            or proof.get('test_sha256')!=validation['test_sha256']
            or proof.get('manifest_sha256')!=validation['manifest_sha256']
            or proof.get('invalid')!=[] or proof.get('killed')!=['allow_stale_query']
            or proof.get('survived')!=['retain_query','allow_stale_status']):
        raise ValueError('exact observed missing controls required')
    if set(proof.get('reports',{}))!={'baseline','retain_query','allow_stale_query','allow_stale_status'}:
        raise ValueError('all four actual mutation runs required')
    for mode,r in proof['reports'].items():
        if r.get('tests')!=4 or r.get('errors')!=0 or r.get('skipped')!=0:
            raise ValueError('actual assertion results, not harness failures, required')
        if r.get('failures')!=(1 if mode=='allow_stale_query' else 0) or r.get('successful') is not (mode!='allow_stale_query'):
            raise ValueError('exact actual kill and survivor results required')
        if r.get('test_sha256')!=validation['test_sha256']:
            raise ValueError('immutable test identity required')
    if not proof['reports']['baseline'].get('successful') or proof['reports']['allow_stale_query'].get('failures')!=1:
        raise ValueError('passing baseline and killed query mutation required')


def verify(con,config):
    cfg,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(config['maintenance_source'],)).fetchone())
    admission.verify_current(con,cfg);qualify(state,config['control_experiment'])
    if (config['source_task']!=state['author_task'] or config['snapshot']!=state['snapshot']
            or config['diagnostic_sha256']!=digest(config['control_experiment'])
            or config['cto']!=cfg['cto'] or config['author']!=cfg['author']):
        raise ValueError('current approved source and control experiment binding required')


def execute(b,state):
    image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
    volume=state['snapshot']['volume'];labels=b.docker('GET','/volumes/'+volume)['Labels']
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=state['author_task']:
        raise ValueError('controller-owned approved volume required')
    name=b.PREFIX+'-negative-controls-'+uuid.uuid4().hex[:12]
    own={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'negative-controls'}
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',Entrypoint=['python'],
            Cmd=['/u3_negative_controls.py','/candidate',state['validation']['test_sha256'],state['validation']['manifest_sha256']],
            Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],NetworkDisabled=True,Labels=own,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=536870912,PidsLimit=64,Mounts=[dict(Type='volume',Source=volume,Target='/candidate',ReadOnly=True)],
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=128m,mode=1777'})))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+60
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode']!=0:raise ValueError('fixed mutation experiment failed')
                proof=json.loads(b.docker_stdout(name,limit=16384));qualify(state,proof)
                return proof
            time.sleep(.2)
        raise TimeoutError('fixed negative control deadline')
    finally:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and all(info['Config']['Labels'].get(k)==v for k,v in own.items()):b.docker('DELETE','/containers/'+name+'?force=true')


def register(b,source):
    try:from incremental_provisioning import NativeIssues
    except ImportError:from broker.incremental_provisioning import NativeIssues
    with b.LOCK:
        with b.db() as con:
            cfg,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
            admission.verify_current(con,cfg);plans.initialize(con)
            prior=con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(state['author_task'],)).fetchone()
            if prior:
                c,s=map(json.loads,prior);verify(con,c)
                return {'stage':s['stage'],'source_task':c['source_task'],'issue_id':c['issue_id'],'reused':True}
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle planning intake required')
        proof=execute(b,state)
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if fx.remaining_calls()<48:raise ValueError('preserve author and review reserve')
        issues=NativeIssues(settings);parent=issues.request('/issues/'+state['issue_id'])
        issue=issues.ensure(dict(title='U3 negative controls '+digest(proof)[:12],parent_issue_id=state['issue_id'],
            project_id=parent.get('project_id'),stage=1,status='todo',description='Evidence-bound controls: baseline passes; retain_query and allow_stale_status survive. Tests-only planning; no product or release approval.'))
        config=dict(kind='verified_controls_v1',source_task=state['author_task'],maintenance_source=source,
            root=cfg['root'],unit=cfg['unit'],issue_id=issue['id'],cto=cfg['cto'],author=cfg['author'],snapshot=state['snapshot'],
            required_files=cfg['required_files'],diagnostic=proof,diagnostic_sha256=digest(proof),control_experiment=proof,
            criteria=cfg['criteria'])
        with b.db() as con:
            verify(con,config)
            con.execute('INSERT INTO test_decompositions VALUES(?,?,?)',(config['source_task'],json.dumps(config,sort_keys=True),json.dumps({'stage':'pending','deterministic_reads':True})))
            state['controls_followup']={'issue_id':issue['id'],'source_task':config['source_task'],'experiment_sha256':digest(proof),'execution_authorized':False}
            state['next_action']='CTO plans two tests-only controls against approved snapshot; product remains blocked'
            con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return {'stage':'pending','issue_id':issue['id'],'source_task':config['source_task'],'experiment':proof,'execution_authorized':False}
