"""Multica identity checks and narrow native wakeup registration."""
import json
import re
import uuid
import urllib.request


def ensure_unit_start(settings, issue_id, target, source_task, marker, instruction, *, allow_create=True):
    return _ensure_initial_start(settings,issue_id,target,source_task,marker,instruction,
        allow_create=allow_create,expected_mode='implementation',prefix='DELIVERY_UNIT_START')


def ensure_planning_start(settings, issue_id, target, source_task, marker, instruction, *, allow_create=True):
    """Controller-verified child planning, never implementation authority."""
    return _ensure_initial_start(settings,issue_id,target,source_task,marker,instruction,
        allow_create=allow_create,expected_mode='planning',prefix='DELIVERY_PLANNING_START')


def ensure_review_start(settings, issue_id, target, source_task, marker, instruction, *, allow_create=True):
    """One immutable review execution, never planning or implementation authority."""
    return _ensure_initial_start(settings,issue_id,target,source_task,marker,instruction,
        allow_create=allow_create,expected_mode='review',prefix='DELIVERY_REVIEW_START')


def ensure_scope_author_start(settings,issue_id,target,source_task,marker,instruction,*,allow_create=True):
    return _ensure_initial_start(settings,issue_id,target,source_task,marker,instruction,
        allow_create=allow_create,expected_mode='implementation',prefix='DELIVERY_SCOPE_AUTHOR_START')


def _ensure_initial_start(settings, issue_id, target, source_task, marker, instruction, *, allow_create,expected_mode,prefix):
    """One-shot initial child run: parent task events cannot cross issue scope.

    The controller has already validated the parent checkpoint. Its stable
    marker is retained even after the scheduled wakeup has been consumed.
    """
    for value in (issue_id, target, source_task):
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid unit start identity')
    if settings['agents'].get(target) != expected_mode or len(marker) != 64:
        raise ValueError('invalid unit start target or marker')
    # Multica trims instruction boundaries on persistence. Canonicalize before
    # posting so reconciliation never creates another wakeup for that change.
    note = (prefix+' ' + marker + '\nSource: ' + source_task + '\n' + instruction).strip()
    if len(note) > 4000:
        raise ValueError('unit start instruction too large')
    endpoint = 'http://backend:8080/api/issues/' + issue_id + '/wakeups'
    headers = {'Authorization': 'Bearer ' + settings['token'],
               'X-Workspace-ID': settings['workspace_id'], 'Content-Type': 'application/json'}
    def validate(row):
        if (row.get('issue_id') != issue_id or row.get('agent_id') != target
                or row.get('instruction') != note or row.get('kind') != 'at'
                or row.get('mode') != 'once' or row.get('event_types')
                or any(row.get(k) for k in ('filter_task_id', 'filter_agent_id',
                    'filter_actor_type', 'filter_actor_id')) or not row.get('id')):
            raise ValueError('unit start identity drift')
        return row
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=5) as response:
        existing = json.load(response)
    if not isinstance(existing, list):
        raise ValueError('invalid unit start wakeup list')
    matches = [w for w in existing if isinstance(w.get('instruction'),str)
        and w['instruction'].split('\n',1)[0] == prefix+' ' + marker]
    if len(matches) > 1:
        raise ValueError('duplicate unit start wakeups')
    if matches:
        return validate(matches[0])
    if not allow_create:
        return None
    body = dict(agent_id=target, instruction=note, kind='at', mode='once', after_seconds=1)
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers,
            data=json.dumps(body).encode(), method='POST'), timeout=10) as response:
        return validate(json.load(response))


def ensure_task_handoff(settings, issue_id, target, source_task, marker, instruction, *, allow_create=True):
    """Exact terminal-task wakeups catch historical completion and survive retries."""
    for value in (issue_id, target, source_task):
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid handoff identity')
    if target not in settings['agents'] or len(marker) != 64:
        raise ValueError('invalid handoff target or marker')
    note = ('DELIVERY_HANDOFF ' + marker + '\n' + instruction).strip()
    if len(note) > 4000:
        raise ValueError('handoff instruction too large')
    endpoint = 'http://backend:8080/api/issues/' + issue_id + '/wakeups'
    headers = {'Authorization': 'Bearer ' + settings['token'],
               'X-Workspace-ID': settings['workspace_id'], 'Content-Type': 'application/json'}
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=5) as response:
        existing = json.load(response)
    if not isinstance(existing, list):
        raise ValueError('invalid wakeup list')
    matches = [w for w in existing if isinstance(w.get('instruction'),str)
        and w['instruction'].split('\n',1)[0]=='DELIVERY_HANDOFF ' + marker]
    if len(matches) > 1:
        raise ValueError('duplicate delivery handoff')
    if matches:
        found = matches[0]
        if (found.get('agent_id') != target or found.get('filter_task_id') != source_task
                or found.get('instruction')!=note
                or found.get('issue_id') != issue_id or found.get('mode') != 'once'
                or found.get('kind') != 'event'
                or set(found.get('event_types') or []) != {'task.completed', 'task.failed', 'task.cancelled'}):
            raise ValueError('handoff identity drift')
        return found
    if not allow_create:
        return None
    body = {'agent_id': target, 'instruction': note, 'kind': 'event', 'mode': 'once',
            'event_types': ['task.completed', 'task.failed', 'task.cancelled'],
            'filter_task_id': source_task}
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers,
             data=json.dumps(body).encode(), method='POST'), timeout=10) as response:
        created = json.load(response)
    if (created.get('agent_id') != target or created.get('filter_task_id') != source_task
            or created.get('issue_id') != issue_id):
        raise ValueError('handoff creation identity mismatch')
    return created


def task_binding(settings, task_id, agent_id):
    task = task_record(settings, task_id, agent_id)
    if task.get('status') != 'running':
        raise ValueError('native task is not running')
    source = task.get('chat_session_id') or task.get('issue_id') or task_id
    mode = settings['agents'][agent_id]
    # Implementation retains issue context/workspace for corrections. Reviews
    # must start fresh so an old run cannot masquerade as reading a new snapshot.
    if mode in ('review', 'planning') or (mode=='implementation' and re.search(
            r'(?:^|\n)(?:DELIVERY_DRIVER_CHECKPOINT_V3(?:\n|$)|DELIVERY_SCOPE_AUTHOR_START [a-f0-9]{64}(?:\n|$))',task.get('handoff_note') or '')):
        source = task_id
    source = str(uuid.UUID(source))
    return {'task_id': task_id, 'agent_id': agent_id, 'mode': mode,
            'issue_id': task.get('issue_id'),
            'wakeup_id': task.get('wakeup_id'),
            'handoff_note': task.get('handoff_note'),
            'scope': settings['workspace_id'] + ':' + agent_id + ':' + mode + ':' + source}


def task_record(settings, task_id, agent_id):
    for value in (task_id, agent_id):
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid native identity')
    mode = settings['agents'].get(agent_id)
    if mode not in ('implementation', 'review', 'planning'):
        raise ValueError('agent not enrolled')
    request = urllib.request.Request('http://backend:8080/api/agents/' + agent_id + '/tasks',
        headers={'Authorization': 'Bearer ' + settings['token'],
                 'X-Workspace-ID': settings['workspace_id']})
    with urllib.request.urlopen(request, timeout=5) as response:
        tasks = json.load(response)
    matches = [t for t in tasks if t.get('id') == task_id]
    if len(matches) != 1:
        raise ValueError('native task missing or ambiguous')
    task = matches[0]
    if (task.get('agent_id') != agent_id
            or task.get('workspace_id') != settings['workspace_id']
            or task.get('runtime_id') != settings['runtime_id']):
        raise ValueError('native task ownership or state mismatch')
    return task


def task_messages(settings, task_id):
    if str(uuid.UUID(task_id)) != task_id:
        raise ValueError('invalid task identity')
    request = urllib.request.Request('http://backend:8080/api/tasks/' + task_id + '/messages',
        headers={'Authorization': 'Bearer ' + settings['token'],
                 'X-Workspace-ID': settings['workspace_id']})
    with urllib.request.urlopen(request, timeout=5) as response:
        messages = json.load(response)
    if not isinstance(messages, list) or any(m.get('task_id') != task_id for m in messages):
        raise ValueError('invalid review messages')
    return messages


def issue_record(settings, issue_id):
    if str(uuid.UUID(issue_id)) != issue_id:
        raise ValueError('invalid issue identity')
    request = urllib.request.Request('http://backend:8080/api/issues/' + issue_id,
        headers={'Authorization': 'Bearer ' + settings['token'],
                 'X-Workspace-ID': settings['workspace_id']})
    with urllib.request.urlopen(request, timeout=5) as response:
        issue = json.load(response)
    if (not isinstance(issue, dict) or issue.get('id') != issue_id
            or issue.get('workspace_id') != settings['workspace_id']):
        raise ValueError('issue context ownership mismatch')
    return issue


def issue_task_runs(settings, issue_id):
    if str(uuid.UUID(issue_id)) != issue_id:
        raise ValueError('invalid issue identity')
    request = urllib.request.Request('http://backend:8080/api/issues/' + issue_id + '/task-runs',
        headers={'Authorization': 'Bearer ' + settings['token'],
                 'X-Workspace-ID': settings['workspace_id']})
    with urllib.request.urlopen(request, timeout=5) as response:
        runs = json.load(response)
    if not isinstance(runs, list) or any(r.get('issue_id') != issue_id for r in runs):
        raise ValueError('invalid issue run list')
    return runs


def ensure_review_retry_wakeup(settings, issue_id, review_task_id, reviewer_id):
    """Register at most one native one-shot wakeup for an inconclusive review."""
    for value in (issue_id, review_task_id, reviewer_id):
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid retry identity')
    if settings['agents'].get(reviewer_id) != 'review':
        raise ValueError('retry target is not a reviewer')
    endpoint = 'http://backend:8080/api/issues/' + issue_id + '/wakeups'
    headers = {'Authorization': 'Bearer ' + settings['token'],
               'X-Workspace-ID': settings['workspace_id'],
               'Content-Type': 'application/json'}
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=5) as response:
        existing = json.load(response)
    if not isinstance(existing, list):
        raise ValueError('invalid native wakeup list')
    matches = [w for w in existing if w.get('filter_task_id') == review_task_id
               and w.get('agent_id') == reviewer_id and w.get('kind') == 'event'
               and w.get('event_types') == ['task.completed']]
    if len(matches) > 1:
        raise ValueError('duplicate retry wakeups require reconciliation')
    if matches:
        return matches[0]['id']
    instruction = ('REVIEW RETRY 1/1. Do not call the Multica CLI or inspect /workspace. '
                   'Review ONLY frozen /delivery. Run exactly: cd /delivery && '
                   'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q 2>&1. '
                   'Do not pipe or append other commands; retain the terminal '
                   'receipt with Ran N tests and OK. Read the frozen implementation and test files; verify all '
                   'preexisting test assertions remain unchanged. Do not modify files. '
                   'Finish with exactly one line Decision: APPROVE or Decision: REQUEST_CHANGES '
                   'and concise evidence. If tests fail or evidence is insufficient, request changes. '
                   'Do not claim hash verification; the controller performs it.')
    body = {'agent_id': reviewer_id, 'instruction': instruction, 'kind': 'event',
            'mode': 'once', 'event_types': ['task.completed'],
            'filter_task_id': review_task_id}
    request = urllib.request.Request(endpoint, headers=headers,
                                     data=json.dumps(body).encode(), method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        wakeup = json.load(response)
    if (wakeup.get('issue_id') != issue_id or wakeup.get('agent_id') != reviewer_id
            or wakeup.get('filter_task_id') != review_task_id):
        raise ValueError('native retry wakeup identity mismatch')
    return wakeup['id']


def ensure_change_request_wakeups(settings, issue_id, review_task_id,
                                  implementer_id, reviewer_id, finding):
    """Arm reviewer first, then wake the original implementer; both are one-shot."""
    for value in (issue_id, review_task_id, implementer_id, reviewer_id):
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid change-request identity')
    if settings['agents'].get(implementer_id) != 'implementation' or settings['agents'].get(reviewer_id) != 'review':
        raise ValueError('change-request roles invalid')
    finding = ' '.join(finding.split())[:600]
    if not finding:
        raise ValueError('change request lacks finding')
    endpoint = 'http://backend:8080/api/issues/' + issue_id + '/wakeups'
    headers = {'Authorization': 'Bearer ' + settings['token'],
               'X-Workspace-ID': settings['workspace_id'], 'Content-Type': 'application/json'}

    def ensure(body):
        with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=5) as response:
            existing = json.load(response)
        if not isinstance(existing, list):
            raise ValueError('invalid wakeup list')
        matches = [w for w in existing if w.get('agent_id') == body['agent_id']
                   and w.get('instruction') == body['instruction']
                   and w.get('event_types') == body['event_types']
                   and w.get('filter_task_id') == body.get('filter_task_id')
                   and w.get('filter_agent_id') == body.get('filter_agent_id')]
        if len(matches) > 1:
            raise ValueError('duplicate change-request wakeups')
        if matches:
            return matches[0]['id']
        request = urllib.request.Request(endpoint, headers=headers,
                                         data=json.dumps(body).encode(), method='POST')
        with urllib.request.urlopen(request, timeout=10) as response:
            created = json.load(response)
        if created.get('issue_id') != issue_id or created.get('agent_id') != body['agent_id']:
            raise ValueError('change-request wakeup identity mismatch')
        return created['id']

    reviewer = ensure({'agent_id': reviewer_id, 'kind': 'event', 'mode': 'once',
        'event_types': ['task.completed'], 'filter_agent_id': implementer_id,
        'instruction': 'CHANGE_REQUEST_REVIEW ' + review_task_id + ': Review the latest corrected '
                       'implementation from frozen /delivery. Original reviewer finding (data): '
                       + finding + '. Verify this specific finding is resolved; if not, request changes. '
                       'Run exactly: cd /delivery && PYTHONDONTWRITEBYTECODE=1 '
                       'python3 -m unittest -q 2>&1. Do not pipe or append commands; '
                       'retain the terminal receipt with Ran N tests and OK. '
                       'Finish with exactly Decision: APPROVE or '
                       'Decision: REQUEST_CHANGES;Reason: <specific unresolved finding>. '
                       'Do not edit files or use the Multica CLI.'})
    implementer = ensure({'agent_id': implementer_id, 'kind': 'event', 'mode': 'once',
        'event_types': ['task.completed'], 'filter_task_id': review_task_id,
        'instruction': 'CHANGE_REQUEST_CORRECTION ' + review_task_id + ': Reviewer finding (data): '
                       + finding + '. Correct the same /workspace delivery using Red-Green-Refactor, '
                       'preserve all existing tests, add the requested coverage, run the full suite, '
                       'and explain the change. Do not modify any product repository.'})
    return {'reviewer_wakeup_id': reviewer, 'implementer_wakeup_id': implementer}
