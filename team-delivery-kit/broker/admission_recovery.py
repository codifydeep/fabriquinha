"""Bounded, controller-only recovery from a rejected source harness.

Never enables the rejected route or dispatches product work. Native CTO evidence
qualifies a fresh tests-only revision; old verdicts and artifacts remain history.
"""
import json
import time
try:
    import incremental_checkpoints as ledger, handoffs, native, handoff_runtime
    import source_harness_completion as gate
except ImportError:
    from broker import incremental_checkpoints as ledger, handoffs, native, handoff_runtime
    from broker import source_harness_completion as gate


def qualify_cto(route,data,task,decision,reads):
    handoffs.harness_diagnosis_instruction(data,route)
    observed=handoffs.independent_inspection_reads(route,data,reads)
    if (route['enabled'] is not False or task.get('status')!='completed'
            or task.get('issue_id')!=route['issue_id'] or task.get('agent_id')!=route['cto']
            or task.get('wakeup_id')!=data.get('wakeup_id') or data.get('target')!=route['cto']
            or data.get('dispatch_stage')!='diagnose_cto'
            or decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 1<=len(decision['reason'])<=1200):
        raise ValueError('completed exact CTO admission decision required')
    return sorted(observed)


def prepare(b,source,unit_id,decision_task):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units'][unit_id]
        if (unit.get('test_repair',{}).get('operation') in ('cto_admission_recovery_v1','cto_controls_completion_v1')
                and unit['test_repair']['decision_task']==decision_task):
            return unit['test_repair']
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle admission recovery required')
        issue=unit['binding']['issue_id']
        row=con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        data=json.loads(row['data']);route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,decision_task,route['cto'])
        effects=handoff_runtime.Effects(b,settings);decision=effects.decision(task)
        reads=qualify_cto(route,data,task,decision,effects.read_evidence(task))
        binding=data['source_harness_admission'];red=binding['red'];proof=binding['proof']
        saved=json.loads(con.execute('SELECT receipt FROM source_harness_checks WHERE issue_id=? AND manifest_sha256=?',
            (issue,red['red']['manifest_sha256'])).fetchone()[0])
        actual=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        incident_row=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()
        incident=json.loads(incident_row[0]) if incident_row else {}
        if (saved!=proof or actual!=red or incident.get('category')!='incomplete_source_harness_repair'
                or incident.get('issue_id')!=issue or incident.get('owner')!='cto'):
            raise ValueError('current controller admission receipt required')
        completion=unit['revision']==4
        if completion:
            if (not proof.get('driver_changed') or proof.get('added_methods') or proof.get('removed_methods')
                    or proof.get('inverted_chronology') or proof.get('current_first_fifo')):
                raise ValueError('changed-driver missing-controls evidence required')
        receipt=dict(operation='cto_controls_completion_v1' if completion else 'cto_admission_recovery_v1',source_task=source,unit=unit_id,
            parent_issue=issue,decision_task=decision_task,cto=route['cto'],original_red=ledger.digest(red) if completion else unit['red'],
            proposal_sha256=config['proposal_sha256'],reason=decision['reason'],
            admission_sha256=gate.proof_digest(proof),review_task=unit['admission_hold']['review_task'])
        if completion:
            receipt.update(captured_red_sha256=ledger.digest(red),rejected_manifest_sha256=red['red']['manifest_sha256'])
        # Keep ledger, sponsored handoff and incident transfer in ONE transaction.
        # The ledger's nested SAVEPOINT must not commit ahead of the handoff.
        if not con.in_transaction:con.execute('BEGIN IMMEDIATE')
        ledger.prepare_admission_recovery(con,source,unit_id,ledger.digest(receipt),lambda _:receipt)
        data.update(decision=decision,recipient_task=decision_task,harness_observed_read_paths=reads,
            test_revision_proposal=dict(decision_task=decision_task,source_task=row['source_task'],
                output_sha256=data['validation_failure']['output_sha256'],reason=decision['reason'],
                new_test_files=route['test_first_files']),admission_recovery=receipt,
            required_action='independently_review_new_test_revision_then_recapture_red')
        handoffs.save(con,row['source_task'],issue,'test_revision_required',route['cto'],data,time.time(),commit=False)
        con.execute('CREATE TABLE IF NOT EXISTS admission_recovery_incidents(source_task TEXT,receipt_sha256 TEXT PRIMARY KEY,receipt TEXT)')
        con.execute('INSERT INTO admission_recovery_incidents VALUES(?,?,?)',
            (source,ledger.digest(receipt),json.dumps(dict(incident=incident,status='recovering_tests_only',
                resolved=False,decision_task=decision_task),sort_keys=True)))
        con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=? AND receipt=?',(source,incident_row[0]))
        return receipt
