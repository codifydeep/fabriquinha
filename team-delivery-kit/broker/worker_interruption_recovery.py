"""Controller-only qualification of a recorded pre-tool SIGKILL after Red.

An offline initialization probe and immutable workspace copy qualify a CTO
decision, not an author retry. Probe intent precedes side effects; an uncertain
dispatch is only observed, never repeated. No worker-facing endpoint exists.
"""
import json
import time
import uuid
try:
    import handoffs, native, handoff_runtime, host_restart_recovery
except ImportError:
    from broker import handoffs, native, handoff_runtime, host_restart_recovery


def qualified(con, issue, source, data):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='worker_interruption_recoveries'").fetchone():
        return False
    row = con.execute('SELECT receipt FROM worker_interruption_recoveries WHERE issue_id=?', (issue,)).fetchone()
    receipt = json.loads(row[0]) if row else {}
    return bool(receipt and receipt == data.get('worker_interruption_recovery')
                and receipt.get('stage') == 'qualified_cto_decision'
                and receipt.get('request', {}).get('source_task') == source
                and receipt.get('request', {}).get('issue_id') == issue
                and receipt.get('author_retry_authorized') is False
                and receipt.get('delivery_approval') is False
                and receipt.get('probe_status') == 'passed'
                and receipt.get('phase_evidence') == data.get('phase_evidence'))


def resume_rejected_probe_admission(b, payload):
    """Operator-only repair of local pre-admission rejection, not unknown Docker dispatch.

submit() commits its lease before every Docker side effect. Absence of both the
lease and exact container proves this request never reached Docker. The same
request UUID is retained; there is no second recovery/probe identity.
"""
    with b.LOCK, b.db() as c:
        row=c.execute('SELECT receipt FROM worker_interruption_recoveries WHERE issue_id=?',
                      (payload['issue_id'],)).fetchone()
        receipt=json.loads(row[0]) if row else {}
        if receipt.get('request') != payload or receipt.get('stage') != 'probe_pending':
            raise ValueError('exact pending local probe intent required')
        if receipt.get('probe_admission_repair'): return receipt
        request=receipt['probe_request']
        if c.execute('SELECT 1 FROM leases WHERE request_id=?',(request,)).fetchone():
            raise ValueError('admitted or uncertain Docker probe must only be observed')
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle admission repair required')
        if b.docker('GET','/containers/'+b.PREFIX+'-job-'+request+'/json'):
            raise ValueError('existing probe container cannot be resubmitted')
        try: b.validate(dict(request_id=request,scenario='acp'))
        except ValueError as error:
            if str(error) != 'unknown fixed scenario': raise
        else: raise ValueError('known local admission rejection required')
        receipt['probe_admission_repair']=dict(operation='local_acp_admission_repair_v1',
            prior_intent=json.loads(row[0]), no_lease=True, no_container=True, at=time.time(),
            author_retry_authorized=False,delivery_approval=False)
        c.execute('UPDATE worker_interruption_recoveries SET receipt=? WHERE issue_id=?',
                  (json.dumps(receipt,sort_keys=True),payload['issue_id']))
        c.commit()  # repair consumed before attempting first Docker admission
        b.submit(dict(request_id=request,scenario='acp'),trusted_acp=True)
        return receipt


def register(b, payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id','source_task','decision_task'}:
        raise ValueError('exact worker recovery identities required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value: raise ValueError('canonical worker identity required')
    issue, source, decision = (payload[k] for k in ('issue_id','source_task','decision_task'))
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS worker_interruption_recoveries(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            old = c.execute('SELECT receipt FROM worker_interruption_recoveries WHERE issue_id=?', (issue,)).fetchone()
            prior = json.loads(old[0]) if old else None
            if prior:
                if prior['request'] != payload: raise ValueError('worker recovery already consumed')
                if prior['stage'] == 'qualified_cto_decision': return prior
            row = handoffs.load(c, source)
            route_row = c.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
            if not row or not route_row: raise ValueError('existing worker incident required')
            route, data = json.loads(route_row[0]), json.loads(row['data'])
            latest = c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1', (issue,)).fetchone()
            if (row['issue_id'] != issue or row['stage'] != 'technical_decision_required'
                    or latest[0] != source or row['owner'] != route['cto'] or not route.get('enabled')
                    or route['author'] == route['cto'] or data.get('error') != 'author_execution_failed'
                    or data.get('source_failure_reason') != 'agent_error.process_failure'
                    or data.get('source_status') != 'failed' or data.get('recipient_task') != decision
                    or data.get('target') != route['cto'] or data.get('decision', {}).get('action') != 'escalate_cto'
                    or data.get('decision', {}).get('optional_files') != []
                    or data.get('validation_failure') or data.get('execution_repair')
                    or data.get('worker_interruption_recovery')):
                raise ValueError('exact escalated failed implementation required')
            bindings = c.execute('SELECT n.*,l.status,l.name FROM native_bindings n JOIN leases l USING(request_id) WHERE task_id=?', (source,)).fetchall()
            if (len(bindings) != 1 or bindings[0]['issue_id'] != issue or bindings[0]['agent_id'] != route['author']
                    or bindings[0]['status'] != 'failed'):
                raise ValueError('exact failed author lease required')
            binding = dict(bindings[0])
            if c.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?', (binding['request_id'],)).fetchone()[0]:
                raise ValueError('pre-tool interruption only')
            active = c.execute("SELECT request_id FROM leases WHERE status IN ('creating','starting','running','closing')").fetchall()
            if any(r[0] != (prior or {}).get('probe_request') for r in active):
                raise ValueError('idle recovery qualification required')
        if b.docker('GET', '/containers/' + binding['name'] + '/json'):
            raise ValueError('interrupted container still exists')
        settings = json.loads((b.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, issue)
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        recipient = next((r for r in runs if r['id'] == decision), None)
        if (not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source
                or next(r for r in authors if r['id'] == source).get('status') != 'failed'
                or not recipient or recipient.get('status') != 'completed' or recipient.get('agent_id') != route['cto']
                or recipient.get('wakeup_id') != data.get('wakeup_id')
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('unchanged failed author and completed independent CTO required')
        phase = handoff_runtime.Effects(b, settings).phase_evidence(source)
        if (not phase or phase != data.get('phase_evidence') or phase.get('phase') != 'implementation'
                or phase.get('red_exit_code') != 1 or phase.get('independent_test_review') != 'approved'
                or not phase.get('frozen_test_hashes')):
            raise ValueError('existing Red and approved frozen tests required')
        # Fixed controller-owned receipt path; never supplied by an agent.
        fault_path = b.STATE / 'fault-injection' / (source + '.json')
        if fault_path.is_symlink(): raise ValueError('fault receipt symlink')
        fault = json.loads(fault_path.read_text())
        if (fault.get('issue_id') != issue or fault.get('task_id') != source
                or fault.get('request_id') != binding['request_id'] or fault.get('signal') != 'SIGKILL'
                or fault.get('accepted_tools_before') != 0 or fault.get('ownership_revalidated') is not True):
            raise ValueError('recorded owned pre-tool SIGKILL required')
        if prior and (prior['worker_image'] != b.IMAGE or prior['fault'] != fault
                      or prior['phase_evidence'] != phase or prior['previous_handoff'] != dict(row)):
            raise ValueError('recovery intent drift')
        if not prior:
            prior = dict(request=payload, stage='probe_pending', probe_request=str(uuid.uuid4()),
                         worker_image=b.IMAGE, fault=fault, phase_evidence=phase, previous_handoff=dict(row),
                         author_retry_authorized=False, delivery_approval=False, at=time.time())
            with b.db() as c:
                if dict(handoffs.load(c, source)) != dict(row): raise ValueError('incident changed')
                c.execute('INSERT INTO worker_interruption_recoveries VALUES (?,?)', (issue, json.dumps(prior, sort_keys=True)))
            b.submit(dict(request_id=prior['probe_request'], scenario='acp'), trusted_acp=True)
        with b.db() as c:
            probe = c.execute('SELECT scenario,status FROM leases WHERE request_id=?', (prior['probe_request'],)).fetchone()
        if not probe or probe['status'] in ('creating','starting','running','closing'):
            if time.time() - prior.get('probe_admission_repair',{}).get('at',prior['at']) > 60:
                raise ValueError('initialization probe unresolved; diagnose without resubmission')
            return prior  # no repeated submit after unknown acknowledgment
        if probe['scenario'] != 'acp' or probe['status'] != 'passed':
            raise ValueError('offline initialization did not pass; retain incident')
        proof = host_restart_recovery.preserve(b, issue, source, binding['scope'], frozen_hashes=phase['frozen_test_hashes'])
        if (proof.get('baseline_unchanged') is not True or proof.get('frozen_tests_unchanged') is not True
                or proof.get('frozen_test_hashes') != phase['frozen_test_hashes']
                or proof.get('delivery_approval') is not False or proof.get('diagnostic_only') is not True):
            raise ValueError('immutable interrupted workspace proof required')
        receipt = dict(prior, stage='qualified_cto_decision', probe_status='passed', proof=proof,
                       operation='pre_tool_worker_interruption_recovery_v1')
        updated = dict(data, worker_interruption_recovery=receipt,
                       diagnostic_revision=source + ':verified-worker-interruption-v1', trigger_task=decision)
        for field in ('recipient_task','wakeup_id','dispatch_marker','dispatch_stage','dispatched_at',
                      'target','instruction','decision','control_error','control_error_count','alerted'):
            updated.pop(field, None)
        with b.db() as c:
            if dict(handoffs.load(c, source)) != dict(row): raise ValueError('incident changed during probe')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('execution started during probe')
            c.execute('UPDATE worker_interruption_recoveries SET receipt=? WHERE issue_id=?', (json.dumps(receipt, sort_keys=True), issue))
            handoffs.save(c, source, issue, 'diagnose_cto', route['cto'], updated, time.time())
        return receipt
