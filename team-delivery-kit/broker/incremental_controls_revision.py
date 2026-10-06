"""Controller-only new tests after an authenticated missing-controls decision."""
import json
import time
try:
    import incremental_checkpoints as ledger,native,handoff_runtime
except ImportError:
    from broker import incremental_checkpoints as ledger,native,handoff_runtime


def prepare(b,source):
    with b.LOCK,b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle controls revision required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1']
        if unit['revision']==5:
            if unit['test_repair']['operation']!='cto_negative_controls_revision_v1':raise ValueError('revision lineage drift')
            return unit['test_repair']
        issue=unit['binding']['issue_id']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()[0])
        plan,result=map(json.loads,con.execute('SELECT config,state FROM incremental_controls_replans WHERE source_task=? AND revision=4',(source,)).fetchone())
        recovery=result.get('terminal_recovery',{})
        proof=plan['proof']
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
        if (route['enabled'] or recovery.get('stage')!='sponsored' or plan['issue_id']!=issue
                or plan['cto']!=route['cto'] or incident.get('owner')!=route['cto']
                or incident.get('category')!='new_negative_control_tests_missing'
                or incident.get('diagnosis')!=proof or incident.get('diagnosis_sha256')!=ledger.digest(proof)
                or proof.get('operation')!='immutable_candidate_missing_controls_diagnosis_v1'
                or proof.get('revision')!=4 or proof.get('new_test_methods')!=proof.get('old_test_methods')
                or proof.get('task_id')!=red['task_id'] or proof.get('manifest_sha256')!=red['red']['manifest_sha256']
                or proof.get('test_sha256')!=red['red']['test_sha256']
                or not trial.get('harness_selector_experiment')
                or trial.get('harness_fixture_volume')!=unit['test_repair']['fixture_volume']):
            raise ValueError('same paused missing-controls evidence required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,recovery['task_id'],route['cto'])
        decision=handoff_runtime.Effects(b,settings).decision(task)
        if (task.get('status')!='completed' or task.get('issue_id')!=issue
                or task.get('wakeup_id')!=recovery['wakeup_id'] or decision!=recovery['decision']
                or decision['action']!='request_test_revision' or decision['optional_files']):
            raise ValueError('authentic current independent CTO decision required')
        if any(r['status'] in ('queued','running') for r in native.issue_task_runs(settings,issue)):
            raise ValueError('idle native controls revision required')
        prior=unit['test_repair']
        receipt=dict(operation='cto_negative_controls_revision_v1',source_task=source,unit='U1',
            parent_issue=issue,decision_task=task['id'],cto=route['cto'],proposal_sha256=config['proposal_sha256'],
            reason=decision['reason'],experiment_sha256=prior['experiment_sha256'],fixture_volume=prior['fixture_volume'],
            diagnosis_sha256=ledger.digest(proof),rejected_manifest_sha256=red['red']['manifest_sha256'])
        data=dict(target=route['cto'],wakeup_id=recovery['wakeup_id'],decision=decision,
            controls_completion=proof,harness_selector_experiment=trial['harness_selector_experiment'],
            harness_fixture_volume=trial['harness_fixture_volume'],
            test_revision_proposal=dict(decision_task=task['id'],reason=decision['reason'],new_test_files=route['test_first_files']))
        with ledger._atomic(con):
            ledger.prepare_controls_revision(con,source,ledger.digest(receipt),lambda _:receipt)
            con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?,?)',
                (task['id'],issue,'test_revision_required',route['cto'],json.dumps(data,sort_keys=True),time.time()))
            con.execute('INSERT INTO delivery_handoff_events(source_task,stage,data,at) VALUES(?,?,?,?)',
                (task['id'],'test_revision_required',json.dumps(data,sort_keys=True),time.time()))
            con.execute('INSERT INTO incremental_runtime_incident_archive VALUES(?,?,?)',(source,4,json.dumps(incident,sort_keys=True)))
            con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=?',(source,))
        return receipt
