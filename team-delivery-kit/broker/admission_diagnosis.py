"""Exact, durable CTO-only dispatch for frozen admission incidents."""
import hashlib,inspect,json,time
try:
    import handoffs,native,handoff_runtime,source_harness_completion as gate
except ImportError:
    from broker import handoffs,native,handoff_runtime,source_harness_completion as gate


def inspect_artifact():
    import hashlib,json,os
    from pathlib import Path
    root=Path('/candidate');manifest=json.loads((root/'manifest.json').read_bytes())['files']
    for path,item in manifest.items():
        f=root/path
        assert not f.is_symlink() and f.is_file()
        assert hashlib.sha256(f.read_bytes()).hexdigest()==item['sha256']
    print(json.dumps({p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in json.loads(os.environ['PATHS'])}))


def dispatch(b,root,unit_id,code_paths):
    with b.LOCK,b.db() as con:
        _,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(root,)).fetchone())
        u=state['units'][unit_id];issue=u['binding']['issue_id']
        if u['revision']!=4 or u['stage']!='awaiting_red' or not u.get('admission_hold'):
            raise ValueError('held controls-completion incident required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle admission diagnosis required')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
        proof=json.loads(con.execute('SELECT receipt FROM source_harness_checks WHERE issue_id=? AND manifest_sha256=?',
            (issue,red['red']['manifest_sha256'])).fetchone()[0])
        incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(root,)).fetchone()[0])
        if incident.get('category')!='incomplete_source_harness_repair' or incident.get('issue_id')!=issue:
            raise ValueError('current admission incident required')
        if (not proof.get('driver_changed') or proof.get('added_methods') or proof.get('removed_methods')
                or proof.get('inverted_chronology') or proof.get('current_first_fifo')):
            raise ValueError('changed-driver missing-controls evidence required')
        paths=sorted(set(route['test_first_files'])|set(code_paths))
        permitted={r[0].removeprefix('/workspace/') for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(issue,))}
        if not 1<=len(code_paths)<=4 or not set(paths)<=permitted:raise ValueError('registered read paths required')
        old=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(red['task_id'],)).fetchone()
        if old and json.loads(old['data']).get('source_harness_admission'):
            data=json.loads(old['data']);hashes=None
            gate.validate_diagnosis(data,route)
            if data.get('wakeup_id'):
                if route['enabled']:raise ValueError('diagnostic route drift')
                return dict(issue_id=issue,wakeup_id=data['wakeup_id'],delivery_approval=False,product_route_enabled=False)
        else:data=None
    if data is None:
        snapshot=b.snapshot_submission({'task_id':red['task_id']})
        name=b.PREFIX+'-controls-inspection-'+red['task_id']
        labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'controls-inspection'}
        volume=b.docker('GET','/volumes/'+snapshot['volume'])
        if volume.get('Labels',{}).get('delivery-kit.source-task')!=red['task_id']:raise ValueError('exact snapshot required')
        if b.docker('GET','/containers/'+name+'/json'):raise ValueError('interrupted inspection')
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='10000:10000',
                Entrypoint=['python3'],Cmd=['-c',inspect.getsource(inspect_artifact)+'\ninspect_artifact()'],
                Env=['PATHS='+json.dumps(paths)],NetworkDisabled=True,Labels=labels,
                HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                    Memory=268435456,PidsLimit=64,Mounts=[dict(Type='volume',Source=snapshot['volume'],Target='/candidate',ReadOnly=True)])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if info and not info['State']['Running']:
                    if info['State']['ExitCode']:raise ValueError('offline hash inspection failed')
                    hashes=json.loads(b.docker_stdout(name,limit=4096));break
                time.sleep(.2)
            else:raise ValueError('inspection deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items()):b.docker('DELETE','/containers/'+name+'?force=true')
        if hashes[route['test_first_files'][0]]!=proof['candidate_test_sha256']:raise ValueError('snapshot and captured Red differ')
        sha=gate.proof_digest(proof);source=red['task_id']
        data=dict(source_task=source,artifact_diagnosis=True,target=route['cto'],dispatch_stage='diagnose_cto',
            source_harness_admission=dict(proof=proof,trial=trial,red=red,candidate_volume=snapshot['volume'],source_task=source),
            validation_failure=dict(category='source_harness_admission_failure',source_task=source,volume=snapshot['volume'],
                output_sha256=sha,diagnostic_read_files=code_paths),
            harness_diagnosis=dict(approval=False,source_task=source,output_sha256=sha,file_sha256=hashes,findings=[
                'The driver changed and known inverted chronology/FIFO fragments are absent. No existing methods were removed.',
                'Required executable negative-control methods for clearing queries and painting stale responses are still absent.',
                'The worker transport stalled after editing because original-read coverage was rearmed on changed lines; proxy53 fixes that phase bug. The partial artifact remains rejected; no Green or approval exists.']))
        instruction=handoffs.harness_diagnosis_instruction(data,route)
        marker=hashlib.sha256((source+':controls-completion:'+sha).encode()).hexdigest()
        data.update(dispatch_marker=marker,trigger_task=source,instruction=instruction)
        with b.LOCK,b.db() as con:
            current=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
            if current!=red:raise ValueError('captured Red drift')
            route['enabled']=False
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),issue))
            handoffs.save(con,source,issue,'dispatch_intent',route['cto'],data,time.time())
    # Only this CTO target/instruction is dispatched; no generic reconcile call.
    settings=json.loads((b.STATE/'native.json').read_text())
    handoffs.harness_diagnosis_instruction(data,route)
    wake=native.ensure_task_handoff(settings,issue,route['cto'],red['task_id'],data['dispatch_marker'],data['instruction'],
        allow_create=handoff_runtime.Effects(b,settings).remaining_calls()>=route['minimum_calls'])
    if wake is None:return dict(issue_id=issue,status='budget_paused',delivery_approval=False,product_route_enabled=False)
    data.update(wakeup_id=wake['id'],dispatched_at=time.time())
    with b.LOCK,b.db() as con:handoffs.save(con,red['task_id'],issue,'awaiting_acceptance',route['cto'],data,time.time())
    return dict(issue_id=issue,wakeup_id=wake['id'],delivery_approval=False,product_route_enabled=False)
