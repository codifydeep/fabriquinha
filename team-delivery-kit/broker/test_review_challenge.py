"""One evidence-backed challenge; preserves rejection and demands fresh review."""
import json
import time
import uuid

try:
    import native, handoffs, test_review_report
except ImportError:
    from broker import native, handoffs, test_review_report


def reopen(broker, payload, *, comparison=None):
    fields = {'issue_id', 'source_task', 'review_task', 'decision_task',
              'manifest_sha256', 'claimed_missing_method'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('exact contradicted review identity required')
    for key in ('issue_id', 'source_task', 'review_task', 'decision_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('canonical challenge identity required')
    claim = payload['claimed_missing_method']
    if not isinstance(claim, str) or not 1 <= len(claim) <= 200:
        raise ValueError('bounded missing-method claim required')
    comparison = comparison or test_review_report.create
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS test_review_challenges(issue_id TEXT PRIMARY KEY, receipt TEXT)')
        old = con.execute('SELECT receipt FROM test_review_challenges WHERE issue_id=?', (payload['issue_id'],)).fetchone()
        if old:
            saved = json.loads(old[0])
            if saved['request'] != payload:
                raise ValueError('one challenge only; identity drift')
            return {'resumed': True, 'issue_id': payload['issue_id']}
        row = con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?', (payload['issue_id'],)).fetchone()
        if not row:
            raise ValueError('rejected review missing')
        config, state = json.loads(row['config']), json.loads(row['state'])
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (payload['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('challenge requires paused idle route')
        diagnosis = state.get('rejection_diagnosis') or {}
        if (state.get('status') != 'blocked' or state.get('challenge_retry')
                or state.get('source_task') != payload['source_task']
                or state.get('review_task') != payload['review_task']
                or state.get('manifest_sha256') != payload['manifest_sha256']
                or not state.get('read_evidence') or diagnosis.get('status') != 'revision_required'
                or diagnosis.get('decision_task') != payload['decision_task']
                or claim not in diagnosis.get('decision', {}).get('reason', '')
                or not config.get('old_red')):
            raise ValueError('exact completed contradicted rejection required')
        red = json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (payload['issue_id'],)).fetchone()[0])
        if (red['task_id'] != payload['source_task'] or red['volume'] != state.get('candidate_volume')
                or red['red']['manifest_sha256'] != payload['manifest_sha256']
                or config['old_red']['volume'] != state.get('previous_volume')
                or set(red['red']['test_sha256']) != set(route['test_first_files'])):
            raise ValueError('frozen challenge identity drift')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        if any(r.get('status') in ('queued', 'running') for r in runs):
            raise ValueError('native tasks must be idle')
        for key, actor in (('review_task', config['reviewer']), ('decision_task', route['cto'])):
            task = next((r for r in runs if r['id'] == payload[key]), None)
            expected_wakeup = state.get('wakeup_id') if key == 'review_task' else diagnosis.get('wakeup_id')
            if (not task or task.get('status') != 'completed' or task.get('agent_id') != actor
                    or task.get('wakeup_id') != expected_wakeup):
                raise ValueError('exact terminal review and CTO required')
        summary = comparison(broker, payload['issue_id'], red, config['old_red'])
        if (summary['candidate_manifest'] != payload['manifest_sha256']
                or summary['previous_manifest'] != config['old_red']['red']['manifest_sha256']
                or set(summary['files']) != set(route['test_first_files'])
                or any(f['removed_methods'] or claim in f['previous_methods'] for f in summary['files'].values())):
            raise ValueError('missing-method claim not contradicted by fixed facts')
        receipt = {'request': payload, 'prior_state': state, 'comparison': summary,
                   'at': time.time(), 'stage': 'fresh_review_required_not_approved'}
        con.execute('INSERT INTO test_review_challenges VALUES (?,?)', (payload['issue_id'], json.dumps(receipt, sort_keys=True)))
        state = {k: v for k, v in state.items() if k not in (
            'wakeup_id', 'dispatched_at', 'reason', 'review_task', 'read_evidence',
            'rejection_diagnosis', 'decision', 'marker')}
        state.update(status='dispatch_intent', challenge_retry=1, evidence_policy=1, comparison=summary)
        con.execute('UPDATE test_revision_trials SET state=? WHERE issue_id=?', (json.dumps(state, sort_keys=True), payload['issue_id']))
        handoffs.save(con, payload['source_task'], payload['issue_id'], 'awaiting_test_revision_review',
                      config['reviewer'], state, time.time())
        return {'resumed': True, 'issue_id': payload['issue_id']}
