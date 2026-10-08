"""Independent incident changes request: immutable history, no execution grant."""
import json
from r3_incident_contract import schema


def record(state, review):
    return dict(proposal=state['proposal'],proposal_sha256=state['proposal_sha256'],review=review,
        diagnosis_task=state['diagnosis_task'],diagnosis_wakeup=state['diagnosis_wakeup'],
        review_task=state['task_id'],review_wakeup=state['wakeup_id'])


def qualify(config,state,review,author_task,review_task,*,accepted_decision='request_changes'):
    from jsonschema import validate
    if state['stage']!='awaiting_review' or review.get('decision')!=accepted_decision:
        raise ValueError('actual independent changes request required')
    author=config['cto' if state.get('escalated') else 'techlead']
    reviewer=config['techlead' if state.get('escalated') else 'cto']
    for task,actor,task_id,wakeup,kind,expected in (
        (author_task,author,state['diagnosis_task'],state['diagnosis_wakeup'],'diagnose',state['proposal']),
        (review_task,reviewer,state['task_id'],state['wakeup_id'],'review',review)):
        if (task.get('id')!=task_id or task.get('wakeup_id')!=wakeup or task.get('agent_id')!=actor
                or task.get('issue_id')!=state['issue_id'] or task.get('status')!='completed'):
            raise ValueError('exact completed independent native submission required')
        output=json.loads(task.get('result',{}).get('output',''))
        validate(output,schema(kind,config['evidence_sha256'],sorted(config['evidence']['facts']),
                               state['proposal_sha256'] if kind=='review' else None))
        if output!=expected:raise ValueError('native submission differs from revision')
    return record(state,review)
