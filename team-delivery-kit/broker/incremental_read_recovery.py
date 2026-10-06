"""One diagnosed pre-tool recovery; no worker-facing administrative endpoint."""
import hashlib
import json
import time
try:
    import native,incremental_checkpoints as ledger
except ImportError:
    from broker import native,incremental_checkpoints as ledger


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS incremental_read_recoveries('
        'source_task TEXT,unit TEXT,revision INTEGER,receipt TEXT,PRIMARY KEY(source_task,unit,revision))')


def authorized(con,issue):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='incremental_read_recoveries'").fetchone():return False
    rows=con.execute('SELECT receipt FROM incremental_read_recoveries').fetchall()
    return any(json.loads(r[0]).get('issue_id')==issue for r in rows)


def authorize(con,config,state,route,task,proof,tool_count,*,now=None):
    """Inputs are native/controller facts obtained by qualify, never agent text."""
    initialize(con);source=config['source_task'];unit=state['units']['U1'];key=(source,'U1',unit['revision'])
    old=con.execute('SELECT receipt FROM incremental_read_recoveries WHERE source_task=? AND unit=? AND revision=?',key).fetchone()
    if old:return json.loads(old[0])
    incident=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()
    incident=json.loads(incident[0]) if incident else {}
    repair=unit.get('test_repair')
    if (not state['execution_authorized'] or unit['stage']!='awaiting_red'
            or (route['enabled'] is not True and not (repair and route['enabled'] is False))
            or task.get('status')!='failed' or task.get('agent_id')!=route['author'] or task.get('issue_id')!=route['issue_id']
            or task.get('error')!='hermes provider error: API call failed after 1 retries'
            or tool_count!=0 or type(tool_count) is not int
            or incident.get('category')!='forced_read_argument_rejected' or incident.get('task_id')!=task['id']
            or incident.get('selected_tool')!='read_file'
            or incident.get('proxy_category') not in (('invalid_forced_argument','incomplete_forced_tool_response') if repair else ('invalid_forced_argument',))
            or incident.get('proxy_status')!=502 or incident.get('proxy_call') is None):
        raise ValueError('exact diagnosed pretool read failure required')
    expected=unit['binding']['materialization']
    empty=hashlib.sha256(b'').hexdigest()
    expected_hashes={expected['new_test']:empty}
    provenance='controller_offline_unwritten_workspace_v1'
    if repair:
        trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(route['issue_id'],)).fetchone()
        trial=json.loads(trial[0]) if trial else {}
        if (trial.get('parent_issue')!=repair['parent_issue'] or trial.get('cto_decision')!=repair['decision_task']
                or trial.get('seed_previous_tests') is not True):
            raise ValueError('exact sponsored seeded trial required')
        expected_hashes=trial['old_red']['red']['test_sha256']
        if set(expected_hashes)!={expected['new_test']}:raise ValueError('seeded test scope drift')
        provenance='controller_offline_unchanged_seeded_workspace_v1'
    if (proof.get('provenance')!=provenance or proof.get('delivery_approval') is not False
            or proof.get('base_manifest_sha256')!=expected['base_manifest_sha256']
            or proof.get('baseline_test_sha256')!=expected['baseline_test_sha256']
            or proof.get('new_test_sha256')!=expected_hashes or proof.get('base_files_verified',0)<len(expected['baseline_test_sha256'])):
        raise ValueError('complete unwritten workspace proof required')
    if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(route['issue_id'],)).fetchone():
        raise ValueError('Red already exists; pretool recovery forbidden')
    receipt=dict(issue_id=route['issue_id'],failed_task=task['id'],author=route['author'],cto=route['cto'],
        inspection=proof,previous_incident=incident,stage='pending',at=time.time() if now is None else now,
        attempt_limit=1,contract='controller_exact_author_reads_v1',delivery_approval=False)
    receipt['marker']=ledger.digest(dict(source=source,unit='U1',revision=unit['revision'],
        failed_task=task['id'],inspection=proof,contract=receipt['contract']))
    with ledger._atomic(con):
        con.execute('INSERT INTO incremental_read_recoveries VALUES(?,?,?,?)',(*key,json.dumps(receipt,sort_keys=True)))
        con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=?',(source,))
        if repair:
            route['enabled']=True
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
                        (json.dumps(route,sort_keys=True),route['issue_id']))
    return receipt


def authorize_write_phase(con,config,state,route,task,proof):
    """Different protocol repair, not a second identical read retry."""
    unit=state['units']['U1'];key=(config['source_task'],'U1',unit['revision'])
    old=json.loads(con.execute('SELECT receipt FROM incremental_read_recoveries WHERE source_task=? AND unit=? AND revision=?',key).fetchone()[0])
    if old.get('write_phase_recovery'):return old
    incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(config['source_task'],)).fetchone()[0])
    failure=old.get('recovery_failure',{})
    if (not unit.get('test_repair') or old.get('stage')!='blocked'
            or not state['execution_authorized'] or unit['stage']!='awaiting_red'
            or route['enabled'] is not False or task.get('status')!='failed'
            or task.get('issue_id')!=route['issue_id'] or task.get('agent_id')!=route['author']
            or task.get('id')!=old.get('failed_recovery_task')
            or task.get('wakeup_id')!=old.get('wakeup_id')
            or task.get('error')!='hermes provider error: API call failed after 1 retries'
            or incident.get('category')!='artifact_write_argument_rejected'
            or incident.get('task_id')!=task['id'] or incident.get('proxy_call')!=failure.get('proxy_call')
            or failure.get('selected_tool')!='write_file' or failure.get('proxy_status')!=502
            or failure.get('proxy_category')!='invalid_forced_argument'
            or proof!=old['inspection'] or proof.get('provenance')!='controller_offline_unchanged_seeded_workspace_v1'):
        raise ValueError('exact seeded write-phase failure and unchanged workspace required')
    previous=dict(old)
    old.update(stage='pending',failed_task=task['id'],at=time.time(),
        prior_failed_tasks=[previous['failed_task']],
        write_phase_recovery=dict(operation='seeded_revision_edit_protocol_v1',attempt_limit=1,
                                  previous_read_recovery=previous,incident=incident))
    old.pop('wakeup_id',None)
    old['marker']=ledger.digest(dict(source=config['source_task'],revision=unit['revision'],
        task=task['id'],inspection=proof,operation='seeded_revision_edit_protocol_v1'))
    with ledger._atomic(con):
        con.execute('UPDATE incremental_read_recoveries SET receipt=? WHERE source_task=? AND unit=? AND revision=?',
                    (json.dumps(old,sort_keys=True),*key))
        route['enabled']=True
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),route['issue_id']))
        con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=?',(config['source_task'],))
    return old


def qualify(b,source,*,write_phase=False):
    """Fixed offline inspection under controller lock before bounded authorization."""
    with b.LOCK,b.db() as con:
        initialize(con)
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1'];issue=unit['binding']['issue_id']
        old=con.execute('SELECT receipt FROM incremental_read_recoveries WHERE source_task=? AND unit=? AND revision=?',(source,'U1',unit['revision'])).fetchone()
        previous=json.loads(old[0]) if old else None
        if old and (not write_phase or previous.get('write_phase_recovery')):return previous
        if write_phase and (not previous or previous.get('stage')!='blocked'):
            raise ValueError('preserved failed read recovery required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():raise ValueError('idle recovery window required')
        incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()[0])
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        settings=json.loads((b.STATE/'native.json').read_text());task=native.task_record(settings,incident['task_id'],route['author'])
        runs=native.issue_task_runs(settings,issue)
        expected_runs={task['id'],previous['failed_task']} if write_phase else {task['id']}
        if {r['id'] for r in runs}!=expected_runs:raise ValueError('exact failed first-unit executions required')
        row=con.execute('SELECT n.scope,n.request_id,l.status,g.mode FROM native_bindings n JOIN leases l USING(request_id) '
            'JOIN grants g USING(request_id) WHERE n.task_id=? ORDER BY g.attempt DESC LIMIT 1',(task['id'],)).fetchone()
        if not row or row['status']!='closed' or row['mode']!='implementation':raise ValueError('closed author lease required')
        count=con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(row['request_id'],)).fetchone()[0]
        if count!=0 and not write_phase:raise ValueError('pretool recovery cannot hide tool execution')
        base=b.issue_base(issue);volume=b.PREFIX+'-work-'+hashlib.sha256(row['scope'].encode()).hexdigest()[:32]
        work=b.docker('GET','/volumes/'+volume)
        if not work or work.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER or work['Labels'].get('delivery-kit.scope')!=row['scope']:
            raise ValueError('recovery workspace ownership mismatch')
        seed=None
        if unit.get('test_repair'):
            try:import test_revision_review
            except ImportError:from broker import test_revision_review
            seed=test_revision_review.seed_source(b,issue)
            if not seed:raise ValueError('registered historical seed required')
        mounts=[dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=volume,Target='/workspace',ReadOnly=True)]
        if seed:mounts.append(seed['mount'])
        name=b.PREFIX+'-unwritten-inspect-'+task['id'];labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':issue,
            'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'unit-recovery-inspection'}
        if b.docker('GET','/containers/'+name+'/json'):raise ValueError('interrupted inspection requires diagnosis')
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,
                User='10000:10000' if seed else '0:0',Entrypoint=['python3'],
                Cmd=['-c','import json,os;from unwritten_unit_inspect import inspect_unwritten;'
                     'print(json.dumps(inspect_unwritten("/base","/workspace",os.environ["EXPECTED"],json.loads(os.environ["NEW_TESTS"]),'
                     '"/previous" if os.environ["SEEDED"]=="1" else None,json.loads(os.environ["SEED_HASHES"])),sort_keys=True))'],
                Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1','EXPECTED='+base['manifest_sha256'],'NEW_TESTS='+json.dumps(route['test_first_files']),
                     'SEEDED='+('1' if seed else '0'),'SEED_HASHES='+json.dumps(seed['selection']['test_sha256'] if seed else None)],
                Labels=labels,NetworkDisabled=True,HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
                    SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=96,Mounts=mounts)))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']!=0:raise ValueError('unwritten inspection failed')
                    proof=json.loads(b.docker_stdout(name));break
                time.sleep(.1)
            else:raise TimeoutError('unwritten inspection deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and info['Config'].get('Labels',{}).get('delivery-kit.owner')==b.OWNER:
                b.docker('DELETE','/containers/'+info['Id']+'?force=true')
        if write_phase:return authorize_write_phase(con,config,state,route,task,proof)
        return authorize(con,config,state,route,task,proof,count)


def reconcile(con,source,unit,effects):
    initialize(con);key=(source,unit['id'],unit['revision'])
    row=con.execute('SELECT receipt FROM incremental_read_recoveries WHERE source_task=? AND unit=? AND revision=?',key).fetchone()
    if not row:return None
    receipt=json.loads(row[0])
    if receipt['stage']=='blocked':raise ValueError('single read recovery exhausted')
    if not receipt.get('wakeup_id'):
        if time.time()-receipt['at']>=600:raise ValueError('read recovery dispatch unattended')
        if effects.remaining_calls()<32 or not effects.implementation_available(receipt['issue_id'],receipt['author']):return receipt
        spec=json.loads(con.execute('SELECT config FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone()[0])
        objective=next(u for u in spec['units'] if u['id']==unit['id'])
        note=('CONTROLLER READ RECOVERY 1/1. Tests only. Prior provider failure produced no artifact. '
            'Controller supplies exact read requests; only actual results qualify. Preserve all existing code/tests. '
            'Objective: '+objective['objective']+'. Criteria: '+','.join(objective['criteria'])+'. No implementation before independent test review.')
        if unit.get('test_repair'):
            note=note.replace('Prior provider failure produced no artifact.',
                'Prior failure executed no tool; historic NEW test seed is verified unchanged.')
            note+=' Preserve assertions and test methods; repair only NEW-test fixture/parser/report mapping. CTO diagnosis: '+unit['test_repair']['reason']
        if receipt.get('write_phase_recovery'):
            note+=' The seeded revision edit protocol replaces the empty-file bootstrap, not the tests. Perform narrow permitted edits after reading the entire historical test.'
        # Durable authorization and stable marker already precede this effect.
        wake=effects.ensure_wakeup(receipt['issue_id'],receipt['author'],receipt['failed_task'],receipt['marker'],note,allow_create=True)
        if wake:
            receipt.update(stage='dispatched',wakeup_id=wake['id'])
            con.execute('UPDATE incremental_read_recoveries SET receipt=? WHERE source_task=? AND unit=? AND revision=?',
                (json.dumps(receipt,sort_keys=True),*key));con.commit()
    return receipt
