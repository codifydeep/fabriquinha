"""Reconcile the authentic completed CTO task after a controller-gate repair."""
import hashlib
import json
import sqlite3
import time

import broker as b
import handoffs
import handoff_runtime
import incremental_test_repair
import native

SOURCE='01a107ac-fb88-728b-b6e3-592e1fde3821'
ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
CTO_TASK='01a107b9-cc53-77a5-88f4-f2a725d2966b'
with b.LOCK,b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    row=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(SOURCE,)).fetchone()
    data=json.loads(row['data'])
    assert row['stage']=='technical_decision_required'
    assert data['required_action']=='cto_verify_independent_finding_before_author_or_test_revision'
    assert data['recipient_task']==CTO_TASK
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
    settings=json.loads((b.STATE/'native.json').read_text())
    effects=handoff_runtime.Effects(b.handoff_context(),settings)
    task=native.task_record(settings,CTO_TASK,route['cto'])
    assert task['status']=='completed' and task['issue_id']==row['issue_id'] and task['wakeup_id']==data['wakeup_id']
    decision=effects.decision(task)
    assert decision['action']=='request_test_revision' and decision['optional_files']==[]
    handoffs.harness_diagnosis_instruction(data,route)
    reads=handoffs.independent_inspection_reads(route,data,effects.read_evidence(task))
    assert reads==data['harness_observed_read_paths']
    backup=b.STATE/'u3-before-harness-gate-reconciliation-20261004.sqlite'
    assert not backup.exists()
    with sqlite3.connect(backup) as target:
        con.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    data['harness_gate_repair']=dict(previous_required_action=data.pop('required_action'),
        completed_cto_task=CTO_TASK,delivery_approval=False,no_new_model_execution=True)
    handoffs.save(con,SOURCE,row['issue_id'],'accepted',route['cto'],data,time.time())
    result=handoffs.reconcile(con,route,native.issue_task_runs(settings,row['issue_id']),effects)
    assert result=='test_revision_required'
receipt=incremental_test_repair.prepare_source_harness_revision(b.handoff_context(),ROOT,'U3')
print(json.dumps(dict(status='revision_3_prepared_not_activated',cto_task=receipt['decision_task'],
    backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),approval=False)))
