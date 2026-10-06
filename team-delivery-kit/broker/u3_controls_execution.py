"""Sequential additive control authors, frozen mutation/CI gates, independent reviews."""
import hashlib,json,time,uuid
try:import native,handoff_runtime,u3_controls_intake as intake,test_decomposition as plans
except ImportError:from broker import native,handoff_runtime,u3_controls_intake as intake,test_decomposition as plans

SOURCE='01a10c12-c3fc-7e90-8256-082682826530'
FILES={'C01':'tests/test_u3_c01_controls.py','C02':'tests/test_u3_c02_controls.py'}
SOURCES=('app/static/app.js','app/static/index.html','tests/test_incremental_u3.py')

def controls_test_command():
    from test_runner_policy import workspace_command
    return workspace_command(['python3','-m','unittest','discover','-s','.','-q'],['.'])

def initialize(con):con.execute('CREATE TABLE IF NOT EXISTS u3_control_executions(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')

def saved(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='u3_control_executions'").fetchone():return None
        row=con.execute('SELECT config,state FROM u3_control_executions WHERE source_task=?',(SOURCE,)).fetchone()
    return tuple(map(json.loads,row)) if row else None

def save(b,c,s):
    with b.db() as con:
        intake.verify(con,c['plan_config'])
        con.execute('UPDATE u3_control_executions SET state=? WHERE source_task=?',(json.dumps(s,sort_keys=True),SOURCE))

def job(b,script,mounts,env):
    image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
    name=b.PREFIX+'-controls-job-'+uuid.uuid4().hex[:12]
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':SOURCE,
        'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'controls-validator'}
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',Entrypoint=['python'],Cmd=[script],
            Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1']+env,NetworkDisabled=True,Labels=labels,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=536870912,PidsLimit=96,Mounts=mounts,Tmpfs={'/tmp':'rw,nosuid,nodev,size=128m,mode=1777'})))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+120
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                output=b.docker_stdout(name,include_stderr=info['State']['ExitCode']!=0,limit=24576)
                if info['State']['ExitCode']!=0:raise ValueError('fixed controls job failed: '+output[-350:])
                return json.loads(output)
            time.sleep(.2)
        raise TimeoutError('controls fixed job deadline')
    finally:
        try:import helper_cleanup
        except ImportError:from broker import helper_cleanup
        helper_cleanup.schedule(b,name,SOURCE)

def owned(b,snapshot,task):
    labels=b.docker('GET','/volumes/'+snapshot['volume'])['Labels']
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task:raise ValueError('owned exact controls snapshot required')
    return dict(Type='volume',Source=snapshot['volume'],ReadOnly=True)

def begin(b,image,qualification):
    with b.LOCK:
        with b.db() as con:
            initialize(con);row=con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(SOURCE,)).fetchone()
            config,plan=map(json.loads,row);intake.verify(con,config)
            if saved(b):return saved(b)[1]
            if plan.get('stage')!='proposal_ready' or plan['certificate'].get('execution_authorized') is not False:raise ValueError('verified nonexecuting CTO proposal required')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle controls admission required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        task=native.task_record(settings,plan['task_id'],config['cto'])
        actual=fx.decomposition_proposal(task)
        cert=plans.validate_result(config,task,actual,fx.read_evidence(task))
        if actual!=plan['decision'] or cert!=plan['certificate'] or task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=plan['wakeup_id']:raise ValueError('actual same CTO authority required')
        if fx.remaining_calls()<48:raise ValueError('48-call controls/review reserve required')
        if (qualification.get('schema')!='additive-registry-probe-v1' or qualification.get('status')!='passed'
                or qualification.get('worker_image')!=image or qualification.get('uid')!=10000
                or qualification.get('network')!='none' or qualification.get('model_calls')!=0
                or qualification.get('delivery_approval') is not False
                or any(qualification.get(k) is not True for k in ('readless_denied','existing_file_write_denied',
                    'direct_terminal_denied','patch_denied','invalid_code_denied','new_test_created','overwrite_denied','source_unchanged','fixture_only'))):
            raise ValueError('qualified actual additive registry required')
        with b.db() as con:
            cfg,maintenance=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(config['maintenance_source'],)).fetchone())
            c={'plan_config':config,'plan':plan,'worker_image':image,'qualification':qualification,
                'author':cfg['author'],'cto':cfg['cto'],'reviewer':maintenance['maintenance_review_receipt']['reviewer'],
                'maintenance_issue':maintenance['issue_id'],'seed':{'snapshot':maintenance['snapshot'],
                    'task_id':maintenance['author_task'],'manifest_sha256':maintenance['validation']['manifest_sha256']},'attempt_limit_per_unit':1}
            if c['reviewer']==c['author'] or settings['agents'].get(c['reviewer'])!='planning':raise ValueError('independent planning reviewer required')
            s={'stage':'unit_dispatch','step':1,'history':[],'owner':c['cto'],'delivery_approval':False,'next_action':'Dispatch C01 tests-only unit'}
            con.execute('INSERT INTO u3_control_executions VALUES(?,?,?)',(SOURCE,json.dumps(c,sort_keys=True),json.dumps(s,sort_keys=True)))
        return s

def current_seed(c,s):return c['seed'] if s['step']==1 else s['history'][0]['seed']

def require_author_artifact_protocol(messages):
    """Native completion is not evidence of a successful tool operation."""
    writes=[m for m in messages if m.get('type')=='tool_result' and m.get('tool')=='write_file']
    if not writes:
        raise ValueError('additive author missing write evidence; CTO diagnosis required')
    if any('additive_test_rejected' in str(m.get('output','')) for m in writes):
        raise ValueError('additive author write rejected; CTO diagnosis required before snapshot')
    if any(str(m.get('content','')).strip().startswith('HTTP 400:') for m in messages if m.get('type')=='text'):
        raise ValueError('additive author transport failed; CTO diagnosis required before snapshot')

def resume_diagnosed_author(b,proof,diagnosis):
    """One explicit changed-contract admission; never retry a blocked run silently."""
    with b.LOCK:
        c,s=saved(b)
        if s.get('diagnosed_protocol_recovery'):return s
        if (s.get('stage')!='blocked' or s.get('step')!=1
                or diagnosis.get('schema')!='u3-hermes-wal-diagnosis-v1'
                or diagnosis.get('task_id')!=s.get('protocol_diagnostic',{}).get('task_id')
                or diagnosis.get('reason')!='only existing unittest harness imports allowed'
                or diagnosis.get('prohibited_import')!='__future__'
                or diagnosis.get('module_assignment') is not True or diagnosis.get('main_guard') is not True
                or diagnosis.get('artifact_exists') is not False):
            raise ValueError('exact blocked additive diagnosis required')
        with b.db() as con:
            intake.verify(con,c['plan_config'])
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle diagnosed admission required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        t=native.task_record(settings,diagnosis['task_id'],c['author'])
        if (t.get('status')!='completed' or t.get('issue_id')!=s['issue_id'] or t.get('wakeup_id')!=s['wakeup_id']
                or t.get('agent_id')!=c['author']):raise ValueError('exact failed author identity required')
        messages=native.task_messages(settings,t['id'])
        if sum(m.get('type')=='tool_result' and m.get('tool')=='write_file'
                and 'additive_test_rejected' in str(m.get('output','')) for m in messages)!=2:
            raise ValueError('two actual rejected writes required')
        image=proof.get('worker_image')
        if (proof.get('schema')!='additive-registry-probe-v1' or proof.get('status')!='passed'
                or proof.get('uid')!=10000 or proof.get('network')!='none' or proof.get('model_calls')!=0
                or proof.get('delivery_approval') is not False or image==c['worker_image']
                or not isinstance(image,str) or len(image)!=71 or not image.startswith('sha256:')
                or any(proof.get(k) is not True for k in ('readless_denied','existing_file_write_denied',
                    'direct_terminal_denied','patch_denied','invalid_code_denied','new_test_created','overwrite_denied','source_unchanged','fixture_only'))):
            raise ValueError('different qualified additive worker required')
        if fx.remaining_calls()<48:raise ValueError('48-call diagnosed controls/review reserve required')
        note=author_note(c,s)
        if note in (t.get('handoff_note') or ''):raise ValueError('changed instructions required')
        c.update(worker_image=image,qualification=proof)
        marker=intake.digest({'failed_task':t['id'],'diagnosis':diagnosis,'worker':image,'note':note})
        wake=fx.ensure_unit_start(s['issue_id'],c['author'],t['id'],marker,note,allow_create=True)
        if not wake:raise ValueError('diagnosed author wake required')
        s['diagnosed_protocol_recovery']={'failed_task':t['id'],'prior_wakeup':s['wakeup_id'],
            'prior_category':s.get('category'),'diagnosis':diagnosis,'worker_image':image,'scope_id':marker,'attempt_limit':1}
        s.update(stage='awaiting_author',wakeup_id=wake['id'],at=time.time(),owner=c['author'],
            next_action='One diagnosed C01 author; frozen source, full suite, mutations and independent review still required')
        with b.db() as con:
            con.execute('UPDATE u3_control_executions SET config=?,state=? WHERE source_task=?',
                (json.dumps(c,sort_keys=True),json.dumps(s,sort_keys=True),SOURCE))
        return s

def author_note(c,s):
    criterion='C0'+str(s['step']);target='/workspace/'+FILES[criterion]
    objective=next(u['objective'] for u in c['plan']['decision']['units'] if criterion in u['criteria'])
    return ('ADDITIVE CONTROL TEST ONLY. Create exactly ONE new unittest file '+target+'. '
        'One unittest.TestCase with one method '+('test_c01_query_clearing_control' if s['step']==1 else 'test_c02_stale_status_control')+'(self). '
        'Top level permits only imports, the TestCase and an optional docstring. '
        'Put driver strings and constants inside the test method; no module-level assignments, helper functions or __main__ guard. '
        'Allowed imports only: unittest, json, subprocess, shutil, pathlib, tests.test_incremental_u3. '
        'Do not use from __future__ import annotations or any other import. '
        'Use import tests.test_incremental_u3 as u3 (do not import its TestCase directly, which duplicates discovery). '
        'Reuse u3.DRIVER_PREAMBLE, u3.APP_JS_PATH, u3.INDEX_HTML_PATH, u3.NODE_TIMEOUT_SECONDS. '
        'For C01, a separate small Node driver executes SOURCE in context, inputs alpha then blank, '
        'flushes each and records actual calls; Python checks the next board GET omits q=. '
        'For C02, instantiate u3.IncrementalU3QueryMemoryTests, setUpClass and setUp; assert '
        'the recorded rendered_after_stale_status excludes the exact marker STALE OPEN (with a space). '
        'Do not change ANY existing files, tests, driver or product. No terminal/patches. '
        'After full fresh reads call write_file ONCE with complete executable Python (not prose). '
        'Stop after its verified result. Controller freezes, runs full suite and real mutations; '
        'independent review gates the next unit. Mutation failures are not original TDD Red. '
        'No release/product approval. Current objective: '+objective+'\nDELIVERY_TEST_ARTIFACT_V1:'+target+'\n'+
        ''.join('DELIVERY_TEST_SOURCE_V1:/workspace/'+p+'\n' for p in SOURCES)+'DELIVERY_DETERMINISTIC_READ_V1\nDELIVERY_ADDITIVE_CONTROL_V1\n')

def grant(b,issue,task):
    entry=saved(b)
    if not entry:return None
    c,s=entry
    if issue!=s.get('issue_id') or task.get('agent_id')!=c['author']:return None
    if s['stage']!='awaiting_author' or task.get('wakeup_id')!=s.get('wakeup_id') or author_note(c,s) not in (task.get('handoff_note') or ''):raise ValueError('exact active additive author required')
    with b.db() as con:intake.verify(con,c['plan_config'])
    return {'worker_image':c['worker_image'],'policy':s['policy'],'note':author_note(c,s)}

def worker_config(b,request,issue):
    entry=saved(b)
    if not entry or entry[1].get('issue_id')!=issue:return None
    with b.db() as con:r=con.execute('SELECT task_id,agent_id FROM native_bindings WHERE request_id=?',(request,)).fetchone()
    if not r:return None
    settings=json.loads((b.STATE/'native.json').read_text())
    return grant(b,issue,native.task_record(settings,r['task_id'],r['agent_id']))

def dispatch(b,c,s,fx,settings):
    from incremental_provisioning import NativeIssues
    criterion='C0'+str(s['step']);path=FILES[criterion];seed=current_seed(c,s)
    base=b.issue_base(c['maintenance_issue']);issues=NativeIssues(settings)
    parent=issues.request('/issues/'+c['plan_config']['issue_id'])
    child=issues.ensure(dict(title='U3 additive '+criterion+' '+c['plan']['certificate']['proposal_sha256'][:12],
        description='One additive tests-only control. No product permission. '+criterion,parent_issue_id=parent['id'],
        project_id=parent.get('project_id'),stage=s['step'],status='todo'))
    volume=b.PREFIX+'-base-'+child['id'];labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':child['id'],
        'delivery-kit.base-sha':base['base_sha'],'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'controls-base'}
    existing=b.docker('GET','/volumes/'+volume)
    if existing and any(existing['Labels'].get(k)!=v for k,v in labels.items()):raise ValueError('foreign controls base')
    if not existing:b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
    fixture=job(b,'/u3_controls_workspace.py',[dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True),
        dict(owned(b,seed['snapshot'],seed['task_id']),Target='/seed'),dict(Type='volume',Source=volume,Target='/revision',ReadOnly=False)],
        ['BASE_SHA='+base['base_sha'],'SEED_MANIFEST='+seed['manifest_sha256'],'NEW_TEST='+path])
    b.register_issue_base(dict(issue_id=child['id'],base_sha=base['base_sha'],volume=volume,manifest_sha256=fixture['manifest_sha256']))
    b.register_issue_editables(dict(issue_id=child['id'],paths=['/workspace/'+path],test_command=controls_test_command()))
    hashes=job(b,'/u3_controls_sources.py',[dict(owned(b,seed['snapshot'],seed['task_id']),Target='/seed')],['SEED_MANIFEST='+seed['manifest_sha256']])
    s.update(issue_id=child['id'],identifier=child.get('identifier'),fixture=fixture,
        policy={'path':'/workspace/'+path,'criterion':criterion,'sources':hashes},seed=seed)
    note=author_note(c,s);marker=intake.digest({'source':SOURCE,'step':s['step'],'note':note,'seed':seed})
    wake=fx.ensure_unit_start(child['id'],c['author'],seed['task_id'],marker,note,allow_create=fx.remaining_calls()>=40)
    if not wake:raise ValueError('author reserve required')
    s.update(stage='awaiting_author',wakeup_id=wake['id'],at=time.time(),owner=c['author'],next_action='Write one new control; existing files frozen')
    save(b,c,s)

def review_paths(s):return ['/evidence/candidate/'+p for p in (*SOURCES,FILES['C0'+str(s['step'])])]+['/evidence/previous/tests/test_incremental_u3.py']

def mounts(b,binding):
    entry=saved(b)
    if not entry:return []
    c,s=entry
    if s.get('stage')!='awaiting_review' or binding['issue_id']!=s['issue_id'] or binding['agent_id']!=c['reviewer']:return []
    with b.db() as con:r=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
    t=native.task_record(json.loads((b.STATE/'native.json').read_text()),r['task_id'],c['reviewer'])
    if t.get('wakeup_id')!=s['review_wakeup']:raise ValueError('exact additive review wakeup required')
    return [dict(owned(b,s['snapshot'],s['author_task']),Target='/evidence/candidate'),dict(owned(b,s['seed']['snapshot'],s['seed']['task_id']),Target='/evidence/previous')]

def tick(b):
    entry=saved(b)
    if not entry:return
    c,s=entry
    if s['stage'] in ('blocked','controls_review_approved'):return
    with b.LOCK:
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        try:
            with b.db() as con:intake.verify(con,c['plan_config'])
            if s['stage']=='unit_dispatch':dispatch(b,c,s,fx,settings);return
            runs=native.issue_task_runs(settings,s['issue_id'])
            if s['stage']=='awaiting_author':
                matches=[t for t in runs if t.get('wakeup_id')==s['wakeup_id'] and t.get('agent_id')==c['author']]
                if len(matches)>1:raise ValueError('duplicate additive authors')
                if not matches or matches[0]['status'] in ('queued','dispatched','running'):
                    if time.time()-s['at']>1800:raise TimeoutError('additive author deadline')
                    return
                t=matches[0]
                if t['status']!='completed':raise ValueError('author did not complete')
                require_author_artifact_protocol(native.task_messages(settings,t['id']))
                s.update(author_task=t['id'],snapshot=b.snapshot_submission({'task_id':t['id']}),stage='validation_running',validation_started=time.time());save(b,c,s)
                result=job(b,'/u3_controls_validate.py',[dict(owned(b,s['seed']['snapshot'],s['seed']['task_id']),Target='/seed'),dict(owned(b,s['snapshot'],t['id']),Target='/candidate')],
                    ['SEED_MANIFEST='+s['seed']['manifest_sha256'],'CRITERION=C0'+str(s['step']),'STEP='+str(s['step']),'NEW_TEST='+FILES['C0'+str(s['step'])]])
                s.update(validation=result,stage='review_dispatch');save(b,c,s)
            if s['stage']=='validation_running':
                if time.time()-s['validation_started']>180:raise TimeoutError('interrupted controls validation')
                return
            if s['stage']=='review_dispatch':
                digest=s['validation']['manifest_sha256'];note=('INDEPENDENT ADDITIVE TEST REVIEW. Read every declared immutable file completely. '
                    'Verify the new test exercises actual app.js via the existing harness, not constant values or copied product logic. '
                    'All seed files byte-identical. Controller full suite passed '+str(s['validation']['full_suite']['tests'])+' tests. '
                    'Real retain_query mutation killed by C01; existing stale_query still killed. '+('C02 also kills stale_status.' if s['step']==2 else 'C02 is future work, not approved yet.')+
                    ' No writes, terminal or product approval. Return approve_test_revision or reject_test_revision, reason, optional_files=[], manifest_sha256='+digest+'.\n'
                    'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+digest+'\nDELIVERY_TYPED_REVIEW_V1:'+digest+'\nDELIVERY_DETERMINISTIC_READ_V1\n'+
                    ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in review_paths(s)))
                wake=fx.ensure_wakeup(s['issue_id'],c['reviewer'],s['author_task'],intake.digest({'review':s['author_task'],'note':note}),note,allow_create=fx.remaining_calls()>=8)
                if not wake:raise ValueError('review reserve required')
                s.update(stage='awaiting_review',review_wakeup=wake['id'],at=time.time(),owner=c['reviewer'],next_action='Independent exact-snapshot semantic review');save(b,c,s);return
            if s['stage']=='awaiting_review':
                matches=[t for t in runs if t.get('wakeup_id')==s['review_wakeup'] and t.get('agent_id')==c['reviewer']]
                if len(matches)>1:raise ValueError('duplicate controls reviewer')
                if not matches or matches[0]['status'] in ('queued','dispatched','running'):
                    if time.time()-s['at']>1800:raise TimeoutError('controls reviewer deadline')
                    return
                t=matches[0];decision=fx.decision(t);reads=fx.read_evidence(t)
                if t['status']!='completed' or decision.get('action')!='approve_test_revision' or decision.get('manifest_sha256')!=s['validation']['manifest_sha256'] or decision.get('optional_files')!=[]:raise ValueError('controls changes requested or invalid review')
                if any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in review_paths(s)):raise ValueError('complete independent review reads required')
                receipt={'criterion':'C0'+str(s['step']),'author':c['author'],'reviewer':c['reviewer'],'review_task':t['id'],
                    'decision':decision,'validation':s['validation'],'seed':{'task_id':s['author_task'],'snapshot':s['snapshot'],'manifest_sha256':s['validation']['manifest_sha256']},'delivery_approval':False}
                s['history'].append(receipt)
                if s['step']==1:s.update(step=2,stage='unit_dispatch',owner=c['cto'],next_action='Automatically dispatch C02 from independently approved C01')
                else:s.update(stage='controls_review_approved',owner=c['cto'],next_action='Qualify controls as tests-only input for product workflow; no automatic product release')
                save(b,c,s)
        except Exception as error:
            s.update(stage='blocked',category=type(error).__name__,error=str(error)[:350],owner=c['cto'],
                next_action='CTO diagnose the preserved failed execution; no identical replay',delivery_approval=False);save(b,c,s)
