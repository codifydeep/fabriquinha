"""Controller-only exact revision5-to6 sponsorship, never a worker endpoint."""
import json
try:
    import incremental_checkpoints as ledger,native,handoff_runtime
except ImportError:
    from broker import incremental_checkpoints as ledger,native,handoff_runtime


def validate_spike(proof,red):
    if (proof.get('operation')!='frozen_negative_control_spike_v1'
            or proof.get('inputs_unchanged') is not True
            or proof.get('in_memory_hypotheses_only') is not True
            or proof.get('delivery_approval') is not False
            or proof.get('valid_red_green_receipt') is not False
            or proof.get('input_sha256',{}).get('red',{}).get('tests/test_feedback_search_client.py')
                !=red['red']['test_sha256']['tests/test_feedback_search_client.py']):
        raise ValueError('same immutable diagnostic spike required')
    reports=proof.get('reports',{})
    for root in ('red','candidate'):
        r=reports.get(root,{})
        if (r.get('original',{}).get('inside_control',{}).get('canonical_match') is not False
                or r.get('parser_only',{}).get('inside_control',{}).get('accepted') is not True
                or r.get('both',{}).get('inside_control')!={'accepted':False,'canonical_match':True,'rejected_by_predicate':True}):
            raise ValueError('executed causal controls required')
        tests=r['both'].get('test_results',{})
        expected_failed='test_native_search_input_named_search_feedback_is_outside_the_form'
        if len(tests)!=6 or any(type(v) is not bool for v in tests.values()):raise ValueError('complete actual test methods required')
        failures={k for k,v in tests.items() if not v}
        if failures!=({expected_failed} if root=='red' else set()):raise ValueError('original Red and candidate causal comparison required')


def prepare(b,source):
    with b.LOCK,b.db() as c:
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():raise ValueError('idle spike revision required')
        config,state=map(json.loads,c.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone());u=state['units']['U1']
        if u['revision']==6:
            if u['test_repair']['operation']!='cto_negative_spike_revision_v1':raise ValueError('spike lineage drift')
            return u['test_repair']
        issue=u['binding']['issue_id'];route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        row=c.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        if not row or row['stage']!='test_revision_required':raise ValueError('current CTO proposal required')
        d=json.loads(row['data']);sha=d.get('negative_spike_followup');proof=json.loads(c.execute('SELECT receipt FROM incremental_recovery_evidence WHERE source_task=? AND receipt_sha256=?',(source,sha)).fetchone()[0])
        red=json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0]);validate_spike(proof,red)
        if ledger.digest(proof)!=sha:raise ValueError('spike digest drift')
        settings=json.loads((b.STATE/'native.json').read_text());task=native.task_record(settings,d['recipient_task'],route['cto']);decision=handoff_runtime.Effects(b,settings).decision(task)
        if (task.get('status')!='completed' or task.get('issue_id')!=issue or task.get('wakeup_id')!=d['wakeup_id']
                or d.get('target')!=route['cto'] or d.get('decision')!=decision
                or decision['action']!='request_test_revision' or decision['optional_files']
                or (d.get('test_revision_proposal') or {}).get('decision_task')!=task['id']):raise ValueError('authentic current CTO sponsorship required')
        if any(r['status'] in ('running','queued') for r in native.issue_task_runs(settings,issue)):raise ValueError('idle native revision required')
        trial=json.loads(c.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0]);prior=u['test_repair']
        receipt=dict(operation='cto_negative_spike_revision_v1',source_task=source,unit='U1',parent_issue=issue,
            decision_task=task['id'],cto=route['cto'],proposal_sha256=config['proposal_sha256'],reason=decision['reason'],
            experiment_sha256=prior['experiment_sha256'],fixture_volume=prior['fixture_volume'],negative_spike_sha256=sha,
            original_red=u['red'],rejected_manifest_sha256=red['red']['manifest_sha256'])
        with ledger._atomic(c):
            ledger.prepare_negative_spike_revision(c,source,ledger.digest(receipt),lambda _:receipt)
            route['enabled']=False;c.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),issue))
            d.update(negative_control_spike=proof,harness_selector_experiment=trial['harness_selector_experiment'],harness_fixture_volume=trial['harness_fixture_volume'])
            c.execute('UPDATE delivery_handoffs SET data=? WHERE source_task=?',(json.dumps(d,sort_keys=True),row['source_task']))
        return receipt
