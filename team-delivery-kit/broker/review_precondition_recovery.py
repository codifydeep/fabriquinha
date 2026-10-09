"""One fresh review after omitted mandatory reads/suite, never a verdict replay."""
import copy

ERROR = 'ValueError:review_protocol_failure: review approval requires exact offline suite receipt'


def prepare(data, route, recipient, proof):
    source = data.get('source_task')
    if (data.get('review_preconditions_recovery') or data.get('dispatch_stage') != 'ready_review'
            or data.get('target') != route['reviewer'] or data.get('control_error') != ERROR
            or recipient.get('id') != data.get('recipient_task')
            or recipient.get('status') != 'completed' or recipient.get('agent_id') != route['reviewer']
            or recipient.get('issue_id') != route['issue_id']
            or proof.get('operation') != 'omitted_independent_review_preconditions'
            or proof.get('review_task') != recipient['id'] or proof.get('source_task') != source
            or proof.get('manifest_sha256') != data.get('evidence', {}).get('manifest_sha256')
            or proof.get('volume') != data.get('snapshot', {}).get('volume')
            or proof.get('closed_review_lease') is not True
            or proof.get('suite_status') != 'issued' or proof.get('delivery_approval') is not False
            or not proof.get('read_paths') or route['reviewer'] == route['author']):
        raise ValueError('exact unapproved independent review preconditions required')
    result = copy.deepcopy(data)
    result['review_preconditions_recovery'] = dict(proof, attempt_limit=1,
        previous_blocker=copy.deepcopy(data), author_restarted=False)
    result['diagnostic_revision'] = 'missing-independent-review-preconditions-v1'
    result['policy_revalidation'] = True
    result['inspection_revalidation'] = {'read_paths': proof['read_paths']}
    for field in ('instruction','dispatch_marker','dispatch_stage','target','trigger_task',
                  'recipient_task','wakeup_id','dispatched_at','control_error','control_error_count',
                  'decision','required_action','alerted'):
        result.pop(field,None)
    return result
