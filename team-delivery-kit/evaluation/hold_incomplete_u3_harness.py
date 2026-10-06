"""Hold advancement on verified incomplete NEW harness, preserving active work."""
import hashlib
import json
import sqlite3
import time

import broker as b

ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
ISSUE='01a107c0-5936-79be-bf32-6f59017be3eb'
with b.LOCK,b.db() as con:
    con.execute('CREATE TABLE IF NOT EXISTS source_harness_gate_holds(issue_id TEXT PRIMARY KEY,receipt TEXT)')
    con.commit()
    assert not con.execute('SELECT 1 FROM source_harness_gate_holds WHERE issue_id=?',(ISSUE,)).fetchone()
    config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
    assert state['units']['U3']['stage']=='awaiting_green' and state['units']['U3']['revision']==3
    trial_row=con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(ISSUE,)).fetchone()
    trial,review=map(json.loads,trial_row)
    assert review['status']=='approved' and review['review_task']=='01a107ce-da9e-7bef-a9e0-615c79a70552'
    red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    assert red['red']['test_sha256']=={'tests/test_incremental_u3.py':'561798cba594b23c0788891d62ca6eb2442c233f8430a3e82eae4e901608efc4'}
    parent=json.loads(con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',
        ('01a107ac-fb88-728b-b6e3-592e1fde3821',)).fetchone()[0])
    assert parent['test_revision_proposal']['decision_task']==trial['cto_decision']
    assert parent['decision']['action']=='request_test_revision' and parent.get('harness_observed_read_paths')
    backup=b.STATE/'u3-before-incomplete-harness-hold-20261004.sqlite'
    assert not backup.exists()
    with sqlite3.connect(backup) as target:
        con.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    receipt=dict(operation='operator_source_harness_admission_hold_v1',approval=False,
        root=ROOT,issue_id=ISSUE,review_task=review['review_task'],original_review=review,
        candidate_test_sha256=red['red']['test_sha256'],
        candidate_driver_sha256='8c29e4b5ff096e4b871d60747856d5e717f4ab48108f16c1d975917cdd836803',
        previous_driver_sha256='8c29e4b5ff096e4b871d60747856d5e717f4ab48108f16c1d975917cdd836803',
        added_negative_methods=0,owner='cto',
        required_action='complete_new_test_harness_before_product_handoff',at=time.time(),
        backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
    con.execute('INSERT INTO source_harness_gate_holds VALUES(?,?)',(ISSUE,json.dumps(receipt,sort_keys=True)))
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    route['enabled']=False
    con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),ISSUE))
    trial['source_harness_diagnosis']=parent['harness_diagnosis']
    con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),ISSUE))
    state['units']['U3']['admission_hold']=dict(owner='cto',required_action=receipt['required_action'],
        review_task=review['review_task'],delivery_approval=False)
    con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),ROOT))
    con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',(ROOT,json.dumps(dict(
        category='incomplete_source_harness_repair',owner='cto',issue_id=ISSUE,
        required_action=receipt['required_action'],approval=False),sort_keys=True)))
print(json.dumps(dict(status='advancement_held_active_work_preserved',backup_sha256=receipt['backup_sha256'],approval=False)))
