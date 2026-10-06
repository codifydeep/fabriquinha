"""Operator/controller-only sponsorship adapter; no worker-facing endpoint."""
import json
try:
    import incremental_checkpoints as ledger, native, handoff_runtime
except ImportError:
    from broker import incremental_checkpoints as ledger, native, handoff_runtime


def prepare_source_harness_revision(b, source, unit_id):
    """Resolve authentic CTO sponsorship and full source reads, never operator text."""
    try: import handoffs
    except ImportError: from broker import handoffs
    with b.LOCK, b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle source harness revision required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units'][unit_id]
        if unit.get('test_repair',{}).get('operation')=='cto_source_harness_revision_v1':
            return unit['test_repair']
        issue=unit['binding']['issue_id']
        row=con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        if not row or row['stage']!='test_revision_required':
            raise ValueError('current CTO sponsorship required')
        data=json.loads(row['data']);proposal=data['test_revision_proposal']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        handoffs.harness_diagnosis_instruction(data,route)
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,proposal['decision_task'],route['cto'])
        effects=handoff_runtime.Effects(b,settings)
        decision=effects.decision(task)
        reads=handoffs.independent_inspection_reads(route,data,effects.read_evidence(task))
        if (task.get('status')!='completed' or task.get('issue_id')!=issue
                or task.get('wakeup_id')!=data.get('wakeup_id') or data['target']!=route['cto']
                or decision!=data.get('decision') or decision['action']!='request_test_revision'
                or decision['optional_files'] or reads!=data.get('harness_observed_read_paths')
                or proposal['source_task']!=row['source_task'] or proposal['reason']!=decision['reason']
                or proposal['output_sha256']!=data['validation_failure']['output_sha256']):
            raise ValueError('authentic CTO source sponsorship drift')
        receipt=dict(operation='cto_source_harness_revision_v1',source_task=source,unit=unit_id,
            parent_issue=issue,decision_task=task['id'],cto=route['cto'],original_red=unit['red'],
            output_sha256=proposal['output_sha256'],proposal_sha256=config['proposal_sha256'],
            reason=decision['reason'],harness_sha256=ledger.digest(data['harness_diagnosis']))
        ledger.prepare_source_harness_revision(con,source,unit_id,ledger.digest(receipt),lambda _:receipt)
        route['enabled']=False
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),issue))
        return receipt


def prepare(b, source, unit_id='U1'):
    """Pause old route and atomically preserve the verified diagnosis lineage."""
    with b.LOCK, b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle repair preparation required')
        config, state = map(json.loads, con.execute(
            'SELECT config,state FROM incremental_checkpoints WHERE source_task=?', (source,)).fetchone())
        unit = state['units'].get(unit_id)
        if not unit:raise ValueError('declared repair unit required')
        if unit.get('test_repair'):
            return unit['test_repair']
        issue = unit.get('binding', {}).get('issue_id')
        row = con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? '
                          'ORDER BY updated DESC LIMIT 1', (issue,)).fetchone()
        if not row or row[1] != 'test_revision_required':
            raise ValueError('current CTO-sponsored handoff required')
        data = json.loads(row[2]); proposal = data.get('test_revision_proposal', {})
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()[0])
        failure = data.get('validation_failure', {})
        settings = json.loads((b.STATE/'native.json').read_text())
        task = native.task_record(settings, proposal.get('decision_task'), route['cto'])
        decision = handoff_runtime.Effects(b, settings).decision(task)
        if (task.get('status') != 'completed' or task.get('issue_id') != issue
                or task.get('wakeup_id') != data.get('wakeup_id')
                or data.get('target') != route['cto'] or data.get('decision') != decision
                or decision['action'] != 'request_test_revision' or decision['optional_files']
                or failure.get('category') != 'executed_test_failure'
                or proposal.get('source_task') != row[0]
                or proposal.get('reason') != decision['reason']
                or proposal.get('output_sha256') != failure.get('output_sha256')
                or set(proposal.get('new_test_files', [])) != set(route['test_first_files'])):
            raise ValueError('native CTO diagnosis or failure lineage drift')
        if unit_id!='U1':
            required={'/evidence/candidate/'+p for p in
                set(route['test_first_files'])|set(failure.get('diagnostic_read_files',[]))}
            reads=handoff_runtime.Effects(b,settings).read_evidence(task)
            if not required or not required<=set(reads):raise ValueError('observed repair sponsorship reads required')
        receipt = dict(operation='cto_test_repair_v1', source_task=source, unit=unit_id,
            parent_issue=issue, decision_task=task['id'], cto=route['cto'], original_red=unit['red'],
            output_sha256=failure['output_sha256'], proposal_sha256=config['proposal_sha256'],
            reason=decision['reason'])
        ledger.prepare_test_repair(con, source, unit_id, ledger.digest(receipt), lambda _: receipt)
        route['enabled'] = False
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?', (json.dumps(route, sort_keys=True), issue))
        return receipt
