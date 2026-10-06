"""One evidence-bound maintenance revalidation; never approve or edit delivery."""
import json
import re
import time
import uuid
try:
    import handoffs, native
except ImportError:
    from broker import handoffs, native


def reopen(broker, payload):
    keys = {'issue_id', 'source_task', 'review_task', 'manifest_sha256', 'worker_image'}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError('exact review revalidation identity required')
    for key in ('issue_id', 'source_task', 'review_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('canonical task identity required')
    if (not re.fullmatch(r'[a-f0-9]{64}', payload['manifest_sha256'])
            or payload['worker_image'] != broker.IMAGE):
        raise ValueError('revalidation snapshot or worker image drift')
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS review_policy_revalidations('
                    'review_task TEXT PRIMARY KEY, payload TEXT, original TEXT, at REAL)')
        prior = con.execute('SELECT payload FROM review_policy_revalidations WHERE review_task=?',
                            (payload['review_task'],)).fetchone()
        if prior:
            if json.loads(prior[0]) != payload:
                raise ValueError('revalidation identity drift')
            return {'resumed': True, 'source_task': payload['source_task']}
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (payload['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
            raise ValueError('revalidation requires paused idle route')
        row = handoffs.load(con, payload['source_task'])
        if not row or row['issue_id'] != payload['issue_id']:
            raise ValueError('revalidation source handoff missing')
        data = json.loads(row['data'])
        if (data.get('recipient_task') != payload['review_task']
                or data.get('target') != route['reviewer'] or data.get('policy_revalidation')
                or data.get('evidence', {}).get('manifest_sha256') != payload['manifest_sha256']):
            raise ValueError('revalidation must match exact prior review')
        bound = con.execute('SELECT b.volume FROM review_bindings b JOIN native_bindings n '
                            'USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                            (payload['review_task'], route['reviewer'], payload['issue_id'])).fetchone()
        if not bound or bound[0] != data['snapshot']['volume']:
            raise ValueError('review snapshot binding drift')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        task = native.task_record(settings, payload['review_task'], route['reviewer'])
        if task['status'] != 'completed':
            raise ValueError('prior reviewer must have completed')
        messages = native.task_messages(settings, payload['review_task'])
        if not any(m.get('type') == 'tool_result' and m.get('tool') == 'python'
                   and isinstance(m.get('output'), str) and 'Exit code: 0' in m['output']
                   and 'RED reproduction' in m['output'] for m in messages):
            raise ValueError('recorded forbidden Red execution required')
        validation = broker.validate_frozen_delivery(bound[0], payload['source_task'])
        if (validation.get('manifest_sha256') != payload['manifest_sha256']
                or validation.get('baseline_tests_intact') is not True):
            raise ValueError('preserved delivery failed revalidation')
        original_review = con.execute('SELECT * FROM reviews WHERE review_task_id=?',
                                       (payload['review_task'],)).fetchone()
        original = {'handoff': row, 'review': dict(original_review) if original_review else None}
        con.execute('INSERT INTO review_policy_revalidations VALUES (?,?,?,?)',
                    (payload['review_task'], json.dumps(payload, sort_keys=True),
                     json.dumps(original, sort_keys=True), time.time()))
        # Fence late recording of the old task as well as already-saved approval.
        con.execute('INSERT OR IGNORE INTO reviews '
                    '(review_task_id,source_task_id,reviewer_agent_id,manifest_sha256,status) '
                    'VALUES (?,?,?,?,?)', (payload['review_task'], payload['source_task'],
                    route['reviewer'], payload['manifest_sha256'], 'policy_invalidated'))
        con.execute("UPDATE reviews SET status='policy_invalidated' WHERE review_task_id=?",
                    (payload['review_task'],))
        data['policy_revalidation'] = payload
        data['review_retries'] = data.get('review_retries', 0) + 1
        for field in ('recipient_task', 'wakeup_id', 'dispatched_at', 'dispatch_marker',
                      'instruction', 'review', 'alerted'):
            data.pop(field, None)
        handoffs.save(con, payload['source_task'], payload['issue_id'], 'ready_review',
                      route['reviewer'], data, time.time())
        return {'resumed': True, 'source_task': payload['source_task']}
