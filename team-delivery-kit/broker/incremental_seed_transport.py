"""Controller-only materialization of a real CTO-sponsored transport recovery."""
import json
try:
    import incremental_checkpoints as ledger,native,handoff_runtime
except ImportError:
    from broker import incremental_checkpoints as ledger,native,handoff_runtime


def prepare(b,source):
    with b.LOCK,b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle transport recovery required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1']
        if unit['revision']==4:
            if unit['test_repair']['operation']!='cto_seed_transport_revision_v1':raise ValueError('revision lineage drift')
            return unit['test_repair']
        plan,result=map(json.loads,con.execute('SELECT config,state FROM incremental_seed_read_diagnoses WHERE source_task=?',(source,)).fetchone())
        issue=unit['binding']['issue_id'];proof=plan['proof']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        incident=json.loads(con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()[0])
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        if (route['enabled'] or result.get('stage')!='sponsored' or plan['issue_id']!=issue
                or plan['cto']!=route['cto'] or proof['task_id']!=red['task_id']
                or proof.get('operation')!='seeded_read_transport_diagnosis_v1'
                or proof.get('observed_paid_calls')!=0 or proof.get('observed_tool_names')!=['read_file']*11
                or proof.get('observed_proxy_rejection_status')!=400
                or proof.get('old_image_canary')!='rejected_exact_seed_read'
                or proof.get('new_image_canary')!='dispatched_exact_seed_read'
                or incident.get('category')!='seeded_read_dispatch_contract_rejected_before_model'
                or incident.get('transport_diagnosis_sha256')!=ledger.digest(proof)
                or incident.get('expected_test_sha256')!=red['red']['test_sha256']):
            raise ValueError('exact unchanged pre-provider transport incident required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        labels=proxy.get('Config',{}).get('Labels',{}) if proxy else {}
        if (not proxy or proxy['Image']!=proof['fixed_proxy_image']
                or labels.get('com.docker.compose.project')!=b.PREFIX
                or labels.get('com.docker.compose.service')!='model-proxy'):
            raise ValueError('verified fixed proxy must be installed')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,result['task_id'],route['cto'])
        decision=handoff_runtime.Effects(b,settings).decision(task)
        if (task.get('status')!='completed' or task.get('issue_id')!=issue
                or task.get('wakeup_id')!=result['wakeup_id'] or decision!=result['decision']
                or decision['action']!='request_test_revision' or decision['optional_files']):
            raise ValueError('real independent transport sponsorship required')
        if any(r.get('status') in ('queued','running') for r in native.issue_task_runs(settings,issue)):
            raise ValueError('idle native transport recovery required')
        parent=con.execute('SELECT stage,data FROM delivery_handoffs WHERE source_task=?',(task['id'],)).fetchone()
        data=json.loads(parent['data']) if parent else {}
        if not parent or parent['stage']!='test_revision_required' or data.get('seed_read_transport_diagnosis')!=proof:
            raise ValueError('same authentic CTO handoff required')
        prior=unit['test_repair']
        receipt=dict(operation='cto_seed_transport_revision_v1',source_task=source,unit='U1',parent_issue=issue,
            decision_task=task['id'],cto=route['cto'],proposal_sha256=config['proposal_sha256'],reason=decision['reason'],
            experiment_sha256=prior['experiment_sha256'],fixture_volume=prior['fixture_volume'],
            transport_sha256=ledger.digest(proof),rejected_manifest_sha256=red['red']['manifest_sha256'],
            proxy_image=proof['fixed_proxy_image'])
        with ledger._atomic(con):
            ledger.prepare_seed_transport_revision(con,source,ledger.digest(receipt),lambda _:receipt)
            con.execute('INSERT INTO incremental_runtime_incident_archive VALUES(?,?,?)',(source,3,json.dumps(incident,sort_keys=True)))
            con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=?',(source,))
        return receipt
