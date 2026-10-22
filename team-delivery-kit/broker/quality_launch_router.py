"""Dispatch only by durable v2 admission ownership, never agent mode prose."""
import json
try:
    from . import quality_author_launch as author, quality_review_launch as reviewer
    from . import quality_author_admission as admission, quality_test_review as review, native
    from . import quality_implementation_launch as implementation
except ImportError:
    import quality_author_launch as author, quality_review_launch as reviewer
    import quality_author_admission as admission, quality_test_review as review, native
    import quality_implementation_launch as implementation


def resolve(b, request):
    matches = [module for module in (author, reviewer, implementation) if module.owns(b, request)]
    if len(matches) > 1:
        raise ValueError('ambiguous v2 admission ownership')
    return matches[0] if matches else None


def owns(b, request):
    return resolve(b, request) is not None


def adapter(b, request):
    module = resolve(b, request)
    if module is None:
        raise ValueError('registered v2 admission required')
    return module


def current(b, request):
    return adapter(b, request).current(b, request)


def execute(b, token, args, streaming, defer_transport):
    import hashlib
    with b.db() as con:
        row = con.execute('SELECT request_id FROM grants WHERE digest=?',
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row is None:
        raise ValueError('registered v2 capability required')
    return adapter(b, row[0]).execute(b, token, args, streaming, defer_transport)


def open_transport(b, row, result, scope):
    return adapter(b, row['request_id']).open_transport(b, row, result, scope)


def prompt(b, frame, issue, task, correction):
    return adapter(b, task['quality_request_id']).prompt(b, frame, issue, task, correction)


def admit(b, task_id, agent_id):
    settings = json.loads((b.STATE/'native.json').read_text())
    if settings['agents'].get(agent_id) == 'implementation':
        task=native.task_record(settings,task_id,agent_id)
        with b.db() as con:
            implementation.admission.initialize(con)
            rows=con.execute('SELECT source_task,context,state,context_sha256,state_sha256 '
                'FROM quality_implementation_handoffs').fetchall()
        matches=[];registered=False
        for source,raw_context,raw_state,context_sha,state_sha in rows:
            context,state=json.loads(raw_context),json.loads(raw_state)
            review.require(review.quality.digest(context)==context_sha and review.quality.digest(state)==state_sha)
            if context['issue_id']!=task.get('issue_id'):continue
            registered=True
            if (context['author']==agent_id and state['stage']=='awaiting_implementation'
                    and state['wakeup_id']==task.get('wakeup_id')):matches.append(source)
        if registered:
            review.require(len(matches)==1)
            return implementation.admission.admit(b,matches[0],task_id,agent_id)
        return admission.admit(b, task_id, agent_id)
    review.require(settings['agents'].get(agent_id) == 'review'
        and getattr(b, 'QUALITY_REVIEW_ENABLED', False) is True)
    task = native.task_record(settings, task_id, agent_id)
    with b.db() as con:
        review.initialize(con)
        rows = con.execute('SELECT source_task,context,state,context_sha256,state_sha256 FROM quality_test_reviews').fetchall()
    matches = []
    for source, raw_context, raw_state, context_sha, state_sha in rows:
        context, state = json.loads(raw_context), json.loads(raw_state)
        review.require(review.quality.digest(context) == context_sha and review.quality.digest(state) == state_sha)
        if (context['packet']['issue_id'] == task.get('issue_id') and context['reviewer'] == agent_id
                and state['stage'] == 'awaiting_review' and state['wakeup_id'] == task.get('wakeup_id')):
            matches.append(source)
    review.require(len(matches) == 1)
    return review.admit(b, matches[0], task_id, agent_id)
