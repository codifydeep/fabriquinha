"""Read-only, source-bound CTO decomposition; never an author reset or approval."""
import hashlib
import inspect
import json
import time

try:
    import admission_diagnosis, source_harness_completion as gate, test_decomposition
except ImportError:
    from broker import admission_diagnosis, source_harness_completion as gate, test_decomposition


def verify_current(con, config):
    row=con.execute('SELECT state FROM incremental_checkpoints WHERE source_task=?',(config['root'],)).fetchone()
    if not row:raise ValueError('registered root required')
    u=json.loads(row[0])['units'][config['unit']]
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
    incident=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(config['root'],)).fetchone()
    if (u['revision']!=5 or u['stage']!='awaiting_red' or not u.get('admission_hold')
            or u['binding']['issue_id']!=config['issue_id'] or route['enabled']
            or route['author']!=config['author'] or route['cto']!=config['cto']
            or config['author']==config['cto'] or not incident
            or hashlib.sha256(incident[0].encode()).hexdigest()!=config['incident_sha256']):
        raise ValueError('unchanged paused exhausted admission required')
    red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
    proof=json.loads(con.execute('SELECT receipt FROM source_harness_checks WHERE issue_id=? AND manifest_sha256=?',
        (config['issue_id'],red['red']['manifest_sha256'])).fetchone()[0])
    if (red['task_id']!=config['source_task'] or gate.proof_digest(proof)!=config['diagnostic_sha256']
            or proof.get('added_methods') or proof.get('removed_methods')):
        raise ValueError('exact frozen missing-controls evidence required')


def register(b, root, unit):
    with b.LOCK:
        with b.db() as con:
            test_decomposition.initialize(con)
            u=json.loads(con.execute('SELECT state FROM incremental_checkpoints WHERE source_task=?',(root,)).fetchone()[0])['units'][unit]
            issue=u['binding']['issue_id']
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
            source=red['task_id']
            prior=con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(source,)).fetchone()
            if prior:
                config,state=map(json.loads,prior)
                if config.get('kind')!='admission_controls_v1':raise ValueError('conflicting decomposition')
                verify_current(con,config)
                return {'source_task':source,'stage':state['stage'],'delivery_approval':False}
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle SPIKE registration required')
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            proof=json.loads(con.execute('SELECT receipt FROM source_harness_checks WHERE issue_id=? AND manifest_sha256=?',
                (issue,red['red']['manifest_sha256'])).fetchone()[0])
            incident=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(root,)).fetchone()[0]
            if json.loads(incident).get('category')!='incomplete_source_harness_repair':raise ValueError('typed incident required')
            paths=sorted(set(route['test_first_files'])|{'app/static/app.js','app/static/index.html'})
            allowed={r[0].removeprefix('/workspace/') for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(issue,))}
            if not set(paths)<=allowed:raise ValueError('registered read paths required')
            config=dict(kind='admission_controls_v1',root=root,unit=unit,source_task=source,issue_id=issue,
                cto=route['cto'],author=route['author'],required_files=paths,
                incident_sha256=hashlib.sha256(incident.encode()).hexdigest(),diagnostic=proof,
                diagnostic_sha256=gate.proof_digest(proof),
                criteria={'C01':'A real query-clearing control: deliberately retain the old query; prove the clearing assertion detects that defect while the correct clearing behavior passes.',
                    'C02':'A real stale-paint control: deliberately allow an older response to paint after the current response; prove a DOM/state assertion detects that defect while correct generation protection passes.'})
            verify_current(con,config)
        snapshot=b.snapshot_submission({'task_id':source})
        try:import native
        except ImportError:from broker import native
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,issue)
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                or next(r for r in authors if r['id']==source)['status']!='completed'
                or any(r.get('status') in ('queued','running') for r in runs)):
            raise ValueError('exact latest completed author and idle native issue required')
        volume=b.docker('GET','/volumes/'+snapshot['volume'])
        if volume.get('Labels',{}).get('delivery-kit.source-task')!=source or volume['Labels'].get('delivery-kit.owner')!=b.OWNER:
            raise ValueError('controller-owned frozen snapshot required')
        name=b.PREFIX+'-spike-inspection-'+source
        labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'spike-inspection'}
        if b.docker('GET','/containers/'+name+'/json'):raise ValueError('interrupted inspection remains visible')
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='10000:10000',
                Entrypoint=['python3'],Cmd=['-c',inspect.getsource(admission_diagnosis.inspect_artifact)+'\ninspect_artifact()'],
                Env=['PATHS='+json.dumps(paths)],NetworkDisabled=True,Labels=labels,
                HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                    Memory=268435456,PidsLimit=64,Mounts=[dict(Type='volume',Source=snapshot['volume'],Target='/candidate',ReadOnly=True)])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']:raise ValueError('frozen inspection failed')
                    hashes=json.loads(b.docker_stdout(name,limit=4096));break
                time.sleep(.2)
            else:raise ValueError('frozen inspection deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items()):
                b.docker('DELETE','/containers/'+name+'?force=true')
        if hashes[route['test_first_files'][0]]!=proof['candidate_test_sha256']:raise ValueError('snapshot Red mismatch')
        config.update(snapshot=snapshot,file_sha256=hashes)
        with b.db() as con:
            verify_current(con,config)
            con.execute('INSERT INTO test_decompositions VALUES (?,?,?)',
                (source,json.dumps(config,sort_keys=True),json.dumps({'stage':'pending','deterministic_reads':True})))
        return {'source_task':source,'stage':'pending','delivery_approval':False,'execution_authorized':False}


def planning_bindings(con, task_id):
    return con.execute('SELECT n.request_id,g.mode FROM native_bindings n JOIN grants g USING(request_id) WHERE n.task_id=?',
        (task_id,)).fetchall()


def record_completed_escalation(b, source):
    """Reclassify the exact historical CTO refusal without retrying any agent."""
    try:import native,handoff_runtime
    except ImportError:from broker import native,handoff_runtime
    with b.LOCK:
        with b.db() as con:
            config,state=map(json.loads,con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(source,)).fetchone())
            verify_current(con,config)
            if state.get('category')=='cto_scope_escalation':return dict(status=state['category'],reused=True)
            if state.get('stage')!='blocked' or state.get('category')!='invalid_or_unread_decomposition':
                raise ValueError('exact historical failed qualification required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,state['task_id'],config['cto'])
        if task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']:
            raise ValueError('exact native CTO recipient required')
        fx=handoff_runtime.Effects(b,settings);decision=fx.decomposition_proposal(task)
        certificate=test_decomposition.validate_escalation(config,task,decision,fx.read_evidence(task))
        changed={**state,'category':'cto_scope_escalation','decision':decision,'certificate':certificate,
            'previous_qualification_category':state['category'],
            'next_action':'qualify_harness_prerequisites_before_control_author_dispatch'}
        with b.db() as con:
            verify_current(con,config)
            con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',(json.dumps(changed,sort_keys=True),source))
        return dict(status='cto_scope_escalation',owner=config['cto'],delivery_approval=False,execution_authorized=False)


def recover_typed_transport(b, source, expected_proxy):
    """One different, installed transport; failed proposal is never accepted."""
    try:import native,handoff_runtime
    except ImportError:from broker import native,handoff_runtime
    with b.LOCK:
        with b.db() as con:
            config,state=map(json.loads,con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(source,)).fetchone())
            verify_current(con,config)
            if state.get('bounded_adapter_recovery'):return dict(status=state['stage'],reused=True,delivery_approval=False)
            if (config.get('kind')!='admission_controls_v1' or state.get('stage')!='blocked'
                    or state.get('category')!='invalid_or_unread_decomposition'
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('idle exact failed CTO proposal required')
            bindings=planning_bindings(con,state['task_id'])
            if len(bindings)!=1 or bindings[0][1]!='planning':raise ValueError('single read-only planning identity required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,state['task_id'],config['cto'])
        runs=native.issue_task_runs(settings,config['issue_id'])
        if (task.get('status')!='failed' or task.get('wakeup_id')!=state['wakeup_id']
                or any(r.get('status') in ('queued','running') for r in runs)):
            raise ValueError('failed exact native recipient and idle issue required')
        fx=handoff_runtime.Effects(b,settings);reads=fx.read_evidence(task)
        if any(reads.get('/evidence/candidate/'+p,{}).get('lines',0)<=0
                or reads.get('/evidence/candidate/'+p,{}).get('lines')!=reads.get('/evidence/candidate/'+p,{}).get('total_lines')
                for p in config['required_files']):raise ValueError('failed task full reads required')
        # Persisted pre-replacement log receipt is required when new proxy has no old log.
        with b.db() as con:
            stored=con.execute('SELECT receipt FROM admission_spike_transport_failures WHERE source_task=?',(source,)).fetchone()
        if not stored:raise ValueError('preserved proxy rejection required')
        failure=json.loads(stored[0])
        if (failure.get('execution_id')!=bindings[0][0] or failure.get('task_id')!=task['id']
                or failure.get('category')!='nonterminal_or_non_json_response'):
            raise ValueError('exact structured response transport failure required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (proxy.get('Image')!=expected_proxy or expected_proxy==failure['proxy_image']
                or not proxy['State']['Running'] or proxy['Config']['Labels'].get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('different installed scoped transport required')
        if fx.remaining_calls()<8:raise ValueError('CTO budget reserve required')
        replacement=dict(stage='pending',deterministic_reads=True,bounded_adapter_recovery=dict(
            previous=state,failure=failure,proxy_image=expected_proxy,delivery_approval=False))
        with b.db() as con:
            verify_current(con,config)
            con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',(json.dumps(replacement,sort_keys=True),source))
        return dict(status='pending_changed_transport',delivery_approval=False,execution_authorized=False)


def capture_transport_failure(b, source):
    with b.LOCK,b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS admission_spike_transport_failures(source_task TEXT PRIMARY KEY,receipt TEXT)')
        prior=con.execute('SELECT receipt FROM admission_spike_transport_failures WHERE source_task=?',(source,)).fetchone()
        if prior:return json.loads(prior[0])
        config,state=map(json.loads,con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(source,)).fetchone())
        verify_current(con,config)
        if state.get('stage')!='blocked' or state.get('category')!='invalid_or_unread_decomposition':
            raise ValueError('blocked SPIKE transport required')
        execution=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(state['task_id'],)).fetchone()[0]
        events=[]
        for line in b.docker_stdout(b.PREFIX+'-model-proxy-1',limit=262144).splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('execution_id')==execution and event.get('call_number') is not None:events.append(event)
        if (len(events)!=1 or events[0].get('status')!=502
                or events[0].get('category')!='structured_decision_response_invalid'
                or events[0].get('structured_rejection_category')!='nonterminal_or_non_json_response'):
            raise ValueError('one actual structured transport rejection required')
        receipt=dict(source_task=source,task_id=state['task_id'],execution_id=execution,
            category='nonterminal_or_non_json_response',call_number=events[0]['call_number'],
            proxy_image=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')['Image'],
            event_sha256=hashlib.sha256(json.dumps(events[0],sort_keys=True).encode()).hexdigest(),delivery_approval=False)
        con.execute('INSERT INTO admission_spike_transport_failures VALUES (?,?)',(source,json.dumps(receipt,sort_keys=True)))
        return receipt
