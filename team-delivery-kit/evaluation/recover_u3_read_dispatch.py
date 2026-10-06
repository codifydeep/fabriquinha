"""One retry after a proven controller-read contract fix, not product recovery."""
import hashlib,json,sqlite3
import broker as b
import native,handoff_runtime
ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
ISSUE='01a107f1-ecc1-7d54-a56c-8f4c646f07a6'
OLD='01a107f2-8f59-7ea6-90e4-7d48850cc9b3'
PROXY='sha256:c39ae9b33f1f5f98a0c4445d6c78e4c6d121f319b637f2d702beda9cb98e4020'
with b.LOCK,b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    assert b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')['Image']==PROXY
    config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
    u=state['units']['U3'];assert u['revision']==4 and u['stage']=='awaiting_red' and u['binding']['issue_id']==ISSUE
    assert u['admission_hold']['recovery_state']=='tests_only'
    assert not con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(ISSUE,)).fetchone()
    trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    assert trial['seeded_edit_required'] and trial['cto_decision']==u['test_repair']['decision_task']
    settings=json.loads((b.STATE/'native.json').read_text());task=native.task_record(settings,OLD,route['author'])
    assert task['status']=='completed' and task['issue_id']==ISSUE
    request=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(OLD,)).fetchone()[0]
    assert con.execute('SELECT status FROM leases WHERE request_id=?',(request,)).fetchone()[0]=='closed'
    assert con.execute('SELECT sum(tool_count) FROM tool_events WHERE request_id=?',(request,)).fetchone()[0]==0
    sponsor=native.task_record(settings,trial['cto_decision'],route['cto'])
    decision=handoff_runtime.Effects(b.handoff_context(),settings).decision(sponsor)
    assert sponsor['status']=='completed' and decision['action']=='request_test_revision'
    prior=con.execute('SELECT receipt FROM seeded_edit_recoveries WHERE issue_id=?',(ISSUE,)).fetchone()
    if prior:
        receipt=json.loads(prior[0]);assert receipt['previous_task']==OLD and receipt['proxy_image']==PROXY
    else:
        incident=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(ROOT,)).fetchone()
        assert incident and json.loads(incident[0])==dict(category='ValueError',owner='cto',required_action='diagnose_incremental_runtime_binding_or_execution')
        backup=b.STATE/'u3-before-read-dispatch-recovery-20261004.sqlite'
        assert not backup.exists()
        with sqlite3.connect(backup) as target:
            con.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        marker=hashlib.sha256((OLD+':read-dispatch-200-v1').encode()).hexdigest()
        note=('Resume the SAME CTO-sponsored tests-only U3 revision. The first execution closed '
            'without tools or Red because the controller requested200-line reads while its dispatcher '
            'accepted50 only. The dispatcher is fixed and integration-tested; no product/test scope '
            'or iteration limit changed. Inspect sources and the seeded NEW test, correct the entire '
            'driver and add executable negative controls. Preserve baseline/product/assertions. '
            'Complete actual edits, not promises. Controller separately runs Red and independent '
            'review; no approval or Green exists. CTO requirement: '+decision['reason'])
        assert len(note)+82<=4000
        receipt=dict(source_task=ROOT,issue_id=ISSUE,revision=4,previous_task=OLD,request_id=request,
            marker=marker,instruction=note,proxy_image=PROXY,stage='intent',attempt_limit=1,
            previous_incident=json.loads(incident[0]),backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
            delivery_approval=False)
        route['enabled']=False
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),ISSUE))
        con.execute('INSERT INTO seeded_edit_recoveries VALUES(?,?)',(ISSUE,json.dumps(receipt,sort_keys=True)))
        con.commit()
    wake=native.ensure_task_handoff(settings,ISSUE,route['author'],OLD,receipt['marker'],receipt['instruction'])
    receipt.update(wakeup_id=wake['id'],stage='awaiting_author')
    con.execute('UPDATE seeded_edit_recoveries SET receipt=? WHERE issue_id=?',(json.dumps(receipt,sort_keys=True),ISSUE))
    route['enabled']=True
    con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),ISSUE))
    con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=? AND receipt=?',
        (ROOT,json.dumps(receipt['previous_incident'],sort_keys=True)))
print(json.dumps(dict(status='one_changed_protocol_retry',wakeup_id=wake['id'],approval=False,
    backup_sha256=receipt['backup_sha256'])))
