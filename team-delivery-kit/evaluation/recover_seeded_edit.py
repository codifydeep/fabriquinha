"""One changed-protocol retry of an unchanged seed; preserve failed evidence."""
import hashlib
import json
import sqlite3
import time

import broker as b
import handoff_runtime
import native

ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
ISSUE='01a107c0-5936-79be-bf32-6f59017be3eb'
OLD_TASK='01a107c0-a9d6-75db-92fb-98f0f7f85def'
with b.LOCK,b.db() as con:
    con.execute('CREATE TABLE IF NOT EXISTS seeded_edit_recoveries(issue_id TEXT PRIMARY KEY,receipt TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS rejected_seed_red(task_id TEXT PRIMARY KEY,issue_id TEXT,receipt TEXT)')
    con.commit()
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    settings=json.loads((b.STATE/'native.json').read_text())
    config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
    unit=state['units']['U3']
    assert unit['revision']==3 and unit['stage']=='awaiting_red' and unit['binding']['issue_id']==ISSUE
    trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    old=con.execute('SELECT receipt FROM seeded_edit_recoveries WHERE issue_id=?',(ISSUE,)).fetchone()
    if old:
        receipt=json.loads(old[0])
        assert receipt['previous_task']==OLD_TASK and receipt['source_task']==ROOT
    else:
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(ISSUE,)).fetchone()[0])
        assert red['task_id']==OLD_TASK and red['red']['test_sha256']==trial['old_red']['red']['test_sha256']
        task=native.task_record(settings,OLD_TASK,route['author'])
        assert task['status']=='completed' and task['issue_id']==ISSUE
        sponsor=native.task_record(settings,trial['cto_decision'],route['cto'])
        decision=handoff_runtime.Effects(b.handoff_context(),settings).decision(sponsor)
        assert sponsor['status']=='completed' and decision['action']=='request_test_revision'
        assert trial['cto_decision']==unit['test_repair']['decision_task']
        backup=b.STATE/'u3-before-seeded-edit-recovery-20261004.sqlite'
        assert not backup.exists()
        with sqlite3.connect(backup) as target:
            con.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        marker=hashlib.sha256((OLD_TASK+':seeded-actual-patch-v1').encode()).hexdigest()
        instruction=('CTO-sponsored U3 NEW-test harness repair, same scope and base. Previous task '
            'closed without changing the seeded test, so its suite run is preserved as rejected '
            'unchanged seed, NOT new approved Red. Changed execution contract requires an actual '
            'targeted patch after fresh reads. Repair the harness and add negative controls. '
            'Preserve all assertions/methods, baseline and product. No terminal or promise-only '
            'completion. CTO diagnosis: '+decision['reason'])
        assert len(instruction)+82<=4000
        receipt=dict(source_task=ROOT,issue_id=ISSUE,revision=3,previous_task=OLD_TASK,
            cto_decision=trial['cto_decision'],marker=marker,instruction=instruction,
            prior_red=red,backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
            delivery_approval=False,stage='intent',attempt_limit=1)
        con.execute('INSERT INTO rejected_seed_red VALUES(?,?,?)',(OLD_TASK,ISSUE,json.dumps(red,sort_keys=True)))
        con.execute('DELETE FROM test_first_red WHERE issue_id=? AND task_id=?',(ISSUE,OLD_TASK))
        trial['seeded_edit_required']=True
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),ISSUE))
        route['enabled']=False
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),ISSUE))
        incident=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(ROOT,)).fetchone()
        receipt['previous_incident']=json.loads(incident[0]) if incident else None
        con.execute('INSERT INTO seeded_edit_recoveries VALUES(?,?)',(ISSUE,json.dumps(receipt,sort_keys=True)))
        con.commit()
    wake=native.ensure_task_handoff(settings,ISSUE,route['author'],OLD_TASK,
        receipt['marker'],receipt['instruction'])
    receipt.update(wakeup_id=wake['id'],stage='awaiting_author')
    con.execute('UPDATE seeded_edit_recoveries SET receipt=? WHERE issue_id=?',(json.dumps(receipt,sort_keys=True),ISSUE))
    route['enabled']=True
    con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),ISSUE))
    if receipt.get('previous_incident')==dict(category='ValueError',owner='cto',required_action='diagnose_incremental_runtime_binding_or_execution'):
        con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=? AND receipt=?',
            (ROOT,json.dumps(receipt['previous_incident'],sort_keys=True)))
print(json.dumps({'status':'changed_protocol_retry_registered','wakeup_id':wake['id'],
    'backup_sha256':receipt['backup_sha256'],'approval':False}))
