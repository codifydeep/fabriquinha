"""Operator-only invalidation of one proven inadmissible test approval."""
import json
import time
import uuid


def measure(broker,red):
    volume=broker.docker('GET','/volumes/'+red['volume'])
    labels=volume.get('Labels',{}) if volume else {}
    if labels.get('delivery-kit.owner')!=broker.OWNER or labels.get('delivery-kit.test-first-task')!=red['task_id']:
        raise ValueError('measurement volume identity drift')
    job=broker.PREFIX+'-test-size-'+uuid.uuid4().hex[:12]
    own={'delivery-kit.owner':broker.OWNER,'delivery-kit.test-size-task':red['task_id']}
    selection={k:red['red'][k] for k in ('manifest_sha256','test_sha256')}
    broker.docker('POST','/containers/create?name='+job,{
        'Image':broker.IMAGE,'User':'10000:10000','Entrypoint':['python'],
        'Cmd':['/test_size_inspection.py'],'NetworkDisabled':True,
        'Env':['SELECTION_JSON='+json.dumps(selection)],'Labels':own,
        'HostConfig':{'ReadonlyRootfs':True,'NetworkMode':'none','CapDrop':['ALL'],
            'SecurityOpt':['no-new-privileges'],'Memory':134217728,'PidsLimit':16,
            'Mounts':[{'Type':'volume','Source':red['volume'],'Target':'/red','ReadOnly':True}]}})
    try:
        broker.docker('POST','/containers/'+job+'/start')
        deadline=time.time()+20
        while time.time()<deadline:
            state=broker.docker('GET','/containers/'+job+'/json')['State']
            if not state['Running']:
                if state['ExitCode']:raise ValueError('fixed measurement rejected')
                return json.loads(broker.docker_stdout(job))
            time.sleep(.2)
        raise ValueError('measurement deadline')
    finally:
        current=broker.docker('GET','/containers/'+job+'/json')
        if current and all(current['Config'].get('Labels',{}).get(k)==v for k,v in own.items()):
            broker.docker('DELETE','/containers/'+current['Id']+'?force=true')
        elif current:raise ValueError('measurement cleanup identity drift')


def reopen(broker,payload,*,measurement=measure):
    try:
        import native,handoffs
    except ImportError:
        from broker import native,handoffs
    fields={'issue_id','source_task','review_task','manifest_sha256'}
    if not isinstance(payload,dict) or set(payload)!=fields:raise ValueError('exact size recovery identity required')
    for key in ('issue_id','source_task','review_task'):
        if str(uuid.UUID(payload[key]))!=payload[key]:raise ValueError('canonical recovery identity required')
    with broker.LOCK,broker.db() as con:
        row=con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(payload['issue_id'],)).fetchone()
        if not row:raise ValueError('test review missing')
        config,state=json.loads(row['config']),json.loads(row['state'])
        prior=state.get('size_invalidation')
        if prior:
            if prior['request']!=payload:raise ValueError('size invalidation identity drift')
            return prior
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('size recovery requires paused idle route')
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        if (state.get('status')!='approved' or state.get('source_task')!=payload['source_task']
                or state.get('review_task')!=payload['review_task']
                or state.get('manifest_sha256')!=payload['manifest_sha256']
                or red['task_id']!=payload['source_task']
                or red['red']['manifest_sha256']!=payload['manifest_sha256']
                or set(red['red']['test_sha256'])!=set(route['test_first_files'])):
            raise ValueError('exact approved test snapshot required')
        settings=json.loads((broker.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        review=next((r for r in runs if r['id']==payload['review_task']),None)
        if (not review or review['status']!='completed' or review['agent_id']!=config['reviewer']
                or review.get('wakeup_id')!=state.get('wakeup_id')
                or any(r['status'] in ('queued','running') for r in runs)):
            raise ValueError('terminal independent reviewer and idle issue required')
        facts=measurement(broker,red)
        if (facts.get('manifest_sha256')!=payload['manifest_sha256']
                or set(facts.get('files',{}))!=set(red['red']['test_sha256'])
                or any(v.get('sha256')!=red['red']['test_sha256'][k]
                    or type(v.get('bytes')) is not int or not 0<v['bytes']<=65536
                    for k,v in facts['files'].items())):
            raise ValueError('measured snapshot drift')
        oversized={k:v['bytes'] for k,v in facts['files'].items() if v['bytes']>32768}
        if not oversized:raise ValueError('no oversized new test; cannot invalidate verdict')
        receipt={'request':payload,'facts':facts,'oversized_test_bytes':oversized,
            'prior_review':{k:state.get(k) for k in ('status','review_task','reason','read_evidence','decision')},
            'stage':'inadmissible_snapshot_not_review_override'}
        state.update(status='blocked',reason='Measured NEW test exceeds32768-byte final snapshot gate. Author must reduce duplicate harness/comment bulk without removing test methods, assertions or acceptance coverage; new independent review required.',
                     size_invalidation=receipt)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?',(json.dumps(state,sort_keys=True),payload['issue_id']))
        handoffs.save(con,state['source_task'],payload['issue_id'],'test_revision_blocked',route['cto'],state,time.time())
        return receipt
