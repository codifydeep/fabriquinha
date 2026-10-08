"""Lossless rejected-plan context bound to the current controller dispatch."""
import hashlib
import json
import re

PREFIX = 'DELIVERY_REGISTERED_PLAN_REVISION_V1:'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def reference(config, state):
    return PREFIX + config['source_task'] + ':' + digest(state['plan_revisions'][-1])


def expand(note, issue, task, lookup):
    matches = re.findall(re.escape(PREFIX) + r'([A-Za-z0-9-]+):([a-f0-9]{64})', note)
    if len(matches) != 1:
        raise ValueError('single registered plan revision required')
    source, sha = matches[0]
    row = lookup(source)
    if not row:
        raise ValueError('registered planning source missing')
    config, state = json.loads(row['config']), json.loads(row['state'])
    revisions = state.get('plan_revisions') or []
    if (config['source_task'] != source or state.get('issue_id') != issue
            or state.get('stage') != 'awaiting_plan' or task.get('agent_id') != config['cto']
            or not state.get('wakeup_id') or task.get('wakeup_id') != state['wakeup_id']
            or not revisions or digest(revisions[-1]) != sha):
        raise ValueError('exact active planning dispatch required')
    revision = revisions[-1]
    review = revision['review']
    plan_sha = digest(revision['plan'])
    if (revision['plan_sha256'] != plan_sha or review.get('decision') != 'request_changes'
            or review.get('plan_sha256') != plan_sha or review.get('evidence_sha256') != plan_sha
            or review.get('execution_authorized') is not False
            or review.get('release_homologated') is not False):
        raise ValueError('independent rejection of exact prior plan required')
    full = 'CONTROLLER VERIFIED PRIOR PLAN AND INDEPENDENT REVIEW DATA: ' + json.dumps(
        revision, sort_keys=True, separators=(',', ':'))
    result = note.replace(reference(config, state), full)
    if len(result) > 8000:
        raise ValueError('planning revision exceeds qualified note limit')
    return result
