"""One observed read-only probe of a failed review, never a recovered verdict."""
import copy
import hashlib


OBSERVATION_VERSION = 'acp-failure-receipt-v1'


def prepare(state, red, task, reviewer, paths, reads):
    if state.get('transport_observation_recovery'):
        raise ValueError('read-only transport observation already consumed')
    failure = state.get('review_failure', {})
    error = str(task.get('error', ''))
    if (state.get('status') != 'blocked' or state.get('decision') or state.get('review_task')
            or state.get('terminal_contract') != 'typed-review-v1'
            or failure.get('detail') != 'independent test review did not complete'
            or failure.get('task_id') != task.get('id') or task.get('status') != 'failed'
            or task.get('agent_id') != reviewer or task.get('wakeup_id') != state.get('wakeup_id')
            or 'session/prompt' not in error or 'Internal error' not in error
            or 'code=-32603' not in error
            or state.get('source_task') != red['task_id']
            or state.get('candidate_volume') != red['volume']
            or state.get('manifest_sha256') != red['red']['manifest_sha256']
            or not paths or any(type(reads.get(p, {}).get('lines')) is not int
                or reads[p]['lines'] <= 0 or reads[p]['lines'] != reads[p].get('total_lines') for p in paths)):
        raise ValueError('exact failed fully observed immutable review required')
    result = copy.deepcopy(state)
    result['transport_observation_recovery'] = {
        'failed_task': task['id'], 'failed_wakeup': task['wakeup_id'],
        'prior_failure': copy.deepcopy(failure), 'error_sha256': hashlib.sha256(error.encode()).hexdigest(),
        'manifest_sha256': state['manifest_sha256'], 'read_evidence': copy.deepcopy(reads),
        'cause': 'unknown', 'code': -32603, 'attempt_limit': 1,
        'observation_version': OBSERVATION_VERSION, 'approval': False, 'author_restarted': False}
    result['status'] = 'dispatch_intent'
    for key in ('wakeup_id', 'dispatched_at', 'marker', 'reason', 'review_failure', 'read_evidence'):
        result.pop(key, None)
    return result
