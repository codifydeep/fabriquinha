"""Frozen syntax preflight and bounded CTO sponsorship; never functional Red."""
import hashlib
import inspect
import json
import time
try:
    import native,handoff_runtime,admission_controls_spike
except ImportError:
    from broker import native,handoff_runtime,admission_controls_spike


def inspect_syntax():
    import ast,hashlib,json,subprocess
    from pathlib import Path
    root=Path('/candidate');manifest=json.loads((root/'manifest.json').read_bytes())['files']
    path='tests/test_incremental_u3.py';p=root/path
    if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=manifest[path]['sha256']:
        raise ValueError('immutable test hash mismatch')
    raw=p.read_bytes();result=dict(test_sha256=hashlib.sha256(raw).hexdigest(),
        functional_red=False,delivery_approval=False)
    try:tree=ast.parse(raw)
    except SyntaxError as error:
        result.update(python_syntax_valid=False,error_line=error.lineno)
        print(json.dumps(result));return
    drivers=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(x,ast.Name) and x.id=='DRIVER_BODY' for x in n.targets)]
    result.update(python_syntax_valid=True,driver_count=len(drivers))
    if len(drivers)!=1 or not isinstance(drivers[0],str):raise ValueError('single literal driver required')
    checked=subprocess.run(['node','--check'],input=drivers[0],text=True,capture_output=True,timeout=10)
    result.update(node_syntax_valid=checked.returncode==0,
        driver_sha256=hashlib.sha256(drivers[0].encode()).hexdigest(),
        category='syntax_valid_not_functional_evidence' if checked.returncode==0 else 'driver_syntax_error')
    print(json.dumps(result))


def instruction(config):
    return ('CTO: a separate harness prerequisite, NOT another two-control attempt. '
        'The fixed controller preflight confirms Python parses but DRIVER_BODY fails node --check. '
        'Read all three immutable files. Decide whether to sponsor a narrowly scoped tests-only '
        'driver repair before any control or product work. Preserve every existing test method '
        'and assertion. No deleting C10, ignoring errors, changing discovery, product edits, '
        'merge or release approval. Repair must close the real driver constructs and populate '
        'required report keys through executed observations, not fabricated constants. '
        'Require Python and Node syntax checks, harness execution and independent review. '
        'Syntax failure is infrastructure/harness failure, never functional TDD Red. '
        'Missing negative controls remain a later obligation, not waived by this task. '
        'Return action=request_test_revision with a concise repair scope and acceptance in reason, '
        'or escalate_cto with the exact remaining prerequisite. optional_files=[]. '
        'No tools except mounted evidence reads; do not claim repair or tests executed.\n'
        'Controller preflight: '+json.dumps(config['syntax'],sort_keys=True)+'\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'
        +''.join('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/'+p+'\n' for p in config['required_files']))


def qualify(config, state, task, decision, reads):
    if (task.get('status')!='completed' or task.get('agent_id')!=config['cto']
            or task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state.get('wakeup_id')
            or config['cto']==config['author'] or not isinstance(decision,dict)
            or set(decision)!={'action','reason','optional_files'}
            or decision['action'] not in ('request_test_revision','escalate_cto')
            or decision['optional_files']!=[] or not isinstance(decision['reason'],str)
            or not 1<=len(decision['reason'])<=1200):raise ValueError('exact bounded CTO sponsorship required')
    paths=['/evidence/candidate/'+p for p in config['required_files']]
    if any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
            or reads[p]['lines']!=reads[p].get('total_lines') for p in paths):
        raise ValueError('full immutable prerequisite reads required')
    return dict(decision_task=task['id'],source_task=config['source_task'],owner=config['cto'],
        decision_sha256=hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest(),
        syntax_sha256=hashlib.sha256(json.dumps(config['syntax'],sort_keys=True).encode()).hexdigest(),
        execution_authorized=False,delivery_approval=False,read_evidence={p:reads[p] for p in paths})


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS harness_prerequisites(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def register(b, source):
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            old=con.execute('SELECT state FROM harness_prerequisites WHERE source_task=?',(source,)).fetchone()
            if old:return dict(status=json.loads(old[0])['stage'],reused=True)
            config,state=map(json.loads,con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(source,)).fetchone())
            admission_controls_spike.verify_current(con,config)
            if state.get('category')!='cto_scope_escalation' or not state.get('certificate'):
                raise ValueError('authentic CTO prerequisite refusal required')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle prerequisite registration required')
        volume=config['snapshot']['volume'];v=b.docker('GET','/volumes/'+volume)
        if v['Labels'].get('delivery-kit.owner')!=b.OWNER or v['Labels'].get('delivery-kit.source-task')!=source:
            raise ValueError('exact controller-owned snapshot required')
        name=b.PREFIX+'-harness-preflight-'+source
        labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'harness-preflight'}
        if b.docker('GET','/containers/'+name+'/json'):raise ValueError('interrupted preflight remains visible')
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='10000:10000',
                Entrypoint=['python3'],Cmd=['-c',inspect.getsource(inspect_syntax)+'\ninspect_syntax()'],NetworkDisabled=True,Labels=labels,
                HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                    Memory=268435456,PidsLimit=64,Mounts=[dict(Type='volume',Source=volume,Target='/candidate',ReadOnly=True)])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+25
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']:raise ValueError('fixed syntax inspection failed')
                    syntax=json.loads(b.docker_stdout(name,limit=4096));break
                time.sleep(.2)
            else:raise ValueError('syntax inspection deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items()):b.docker('DELETE','/containers/'+name+'?force=true')
        if (syntax['test_sha256']!=config['file_sha256']['tests/test_incremental_u3.py']
                or syntax.get('category')!='driver_syntax_error' or syntax.get('functional_red') is not False):
            raise ValueError('bound invalid-driver prerequisite required')
        config={**config,'syntax':syntax,'previous_cto':state['task_id']}
        with b.db() as con:
            admission_controls_spike.verify_current(con,config)
            con.execute('INSERT INTO harness_prerequisites VALUES (?,?,?)',
                (source,json.dumps(config,sort_keys=True),json.dumps({'stage':'pending'})))
        return dict(status='pending',syntax_category=syntax['category'],delivery_approval=False)


def mounts(b,binding):
    with b.db() as con:
        initialize(con);rows=con.execute('SELECT config,state FROM harness_prerequisites').fetchall()
    for row in rows:
        c,s=map(json.loads,row)
        if c['issue_id']!=binding['issue_id'] or c['cto']!=binding['agent_id'] or s['stage']!='pending' or not s.get('wakeup_id'):continue
        with b.db() as con:
            bound=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
        if not bound:raise ValueError('native prerequisite binding required')
        task=native.task_record(json.loads((b.STATE/'native.json').read_text()),bound[0],binding['agent_id'])
        if task.get('wakeup_id')!=s['wakeup_id']:continue
        volume=c['snapshot']['volume'];labels=b.docker('GET','/volumes/'+volume)['Labels']
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=c['source_task']:
            raise ValueError('immutable prerequisite snapshot identity required')
        return [dict(Type='volume',Source=volume,Target='/evidence/candidate',ReadOnly=True)]
    return []


def tick(b):
    settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
    with b.db() as con:
        initialize(con);rows=con.execute('SELECT config,state FROM harness_prerequisites').fetchall()
    for row in rows:
        config,state=map(json.loads,row)
        if state['stage']!='pending':continue
        with b.LOCK:
            with b.db() as con:admission_controls_spike.verify_current(con,config)
            if not state.get('wakeup_id'):
                marker=hashlib.sha256((config['source_task']+':driver-prerequisite:'+json.dumps(config['syntax'],sort_keys=True)).encode()).hexdigest()
                wake=fx.ensure_wakeup(config['issue_id'],config['cto'],config['source_task'],marker,instruction(config),allow_create=fx.remaining_calls()>=8)
                if not wake:continue
                state.update(wakeup_id=wake['id'],at=time.time())
            else:
                runs=[r for r in native.issue_task_runs(settings,config['issue_id']) if r.get('wakeup_id')==state['wakeup_id'] and r.get('agent_id')==config['cto']]
                if len(runs)>1:state.update(stage='blocked',category='duplicate_cto_recipient')
                elif runs and runs[0]['status'] not in ('queued','running'):
                    try:
                        decision=fx.decision(runs[0]);proof=qualify(config,state,runs[0],decision,fx.read_evidence(runs[0]))
                        state.update(stage='repair_sponsored' if decision['action']=='request_test_revision' else 'blocked',
                            category='tests_only_contract_required' if decision['action']=='request_test_revision' else 'cto_prerequisite_refused',
                            decision=decision,certificate=proof,task_id=runs[0]['id'])
                    except (ValueError,KeyError,TypeError):state.update(stage='blocked',category='invalid_or_unread_prerequisite')
                elif time.time()-state['at']>1800:state.update(stage='blocked',category='cto_deadline')
            with b.db() as con:
                admission_controls_spike.verify_current(con,config)
                con.execute('UPDATE harness_prerequisites SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),config['source_task']))
