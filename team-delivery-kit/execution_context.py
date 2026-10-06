"""Lossless controller-owned context capsule; references confer no authority.

The route database persists this payload immutably. The broker resolves only
the exact registered reference, before constructing the worker prompt. No
agent-supplied URL, path, command or tool permission is accepted here.
"""
import hashlib
import json

FIELDS = {'version', 'description', 'review_instruction', 'sha256'}
MARKER = 'DELIVERY_EXECUTION_CONTEXT_V1'


def freeze(description, review_instruction):
    for text in (description, review_instruction):
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ValueError('bounded complete execution context required')
    body = dict(version=1, description=description, review_instruction=review_instruction)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {**body, 'sha256': digest}


def validate(capsule):
    if not isinstance(capsule, dict) or set(capsule) != FIELDS or type(capsule['version']) is not int or capsule['version'] != 1:
        raise ValueError('exact execution context capsule required')
    if freeze(capsule['description'], capsule['review_instruction']) != capsule:
        raise ValueError('execution context hash mismatch')
    return capsule


def reference(capsule, mode):
    validate(capsule)
    if mode not in ('implementation', 'review'):
        raise ValueError('invalid execution context mode')
    return MARKER + ':' + capsule['sha256'] + ':' + mode


def resolve(capsule, ref, mode):
    if ref != reference(capsule, mode):
        raise ValueError('execution context reference mismatch')
    return capsule['description' if mode == 'implementation' else 'review_instruction']


def registered(con, mode, issue_id, agent_id, description):
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_routes'").fetchone()
    row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                      (issue_id,)).fetchone() if exists else None
    route = json.loads(row[0]) if row else {}
    capsule = route.get('execution_context')
    if capsule is None:
        if isinstance(description, str) and MARKER in description:
            raise ValueError('unregistered execution context reference')
        return None
    agents = {'implementation': [route.get('author')], 'review': [route.get('reviewer')],
              'planning': [route.get('techlead'), route.get('cto')]}
    if route.get('enabled') is not True or agent_id not in agents.get(mode, []):
        raise ValueError('execution context role or route mismatch')
    resolve(capsule, description, 'implementation')
    return capsule
