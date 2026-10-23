"""Fail-closed build hooks for the pinned Hermes loop and ACP text callback."""
from pathlib import Path

LOOP_ANCHOR='''                append_message(messages, final_msg)
                # Make the completed answer durable before leaving the loop —
'''
LOOP_HOOK='''                # Fixed v2 advisory check; same loop/budget, never another task.
                from quality_review_stop import guard as _quality_review_guard
                _quality_feedback = _quality_review_guard(
                    agent, messages, final_response,
                    min(agent.max_iterations - api_call_count, agent.iteration_budget.remaining),
                )
                if _quality_feedback is not None:
                    _quality_note = json.dumps(_quality_feedback, sort_keys=True)
                    _quality_audit = json.dumps({
                        "candidate": final_response[:16384],
                        "candidate_sha256": __import__("hashlib").sha256(final_response.encode()).hexdigest(),
                        "diagnostic": _quality_feedback,
                    }, sort_keys=True)
                    if agent.reasoning_callback:
                        agent.reasoning_callback("QUALITY_REVIEW_COMPLETION_ATTEMPT_V1:" + _quality_audit)
                    append_message(messages, final_msg)
                    if _quality_feedback["blocked"]:
                        final_response = _quality_note
                        append_message(messages, {"role": "assistant", "content": final_response})
                        agent._session_messages = messages
                        _turn_exit_reason = "quality_review_completion_blocked"
                        break
                    append_message(messages, {"role": "user", "content": _quality_note})
                    agent._session_messages = messages
                    final_response = None
                    continue

'''
STREAM_ANCHOR='''            def stream_delta_cb(text: str) -> None:
                nonlocal streamed_message
                if text:
'''
STREAM_HOOK='''            def stream_delta_cb(text: str) -> None:
                nonlocal streamed_message
                # V2 review exposes only the final answer, not rejected drafts.
                # Tool and thought callbacks remain unchanged for evidence/UI.
                if __import__("quality_review_stop").enabled():
                    return
                if text:
'''
SESSION_ANCHOR='        agent = AIAgent(**kwargs)\n'
SESSION_HOOK='''        # V2 workers share one fixed budget, including completion feedback.
        from quality_review_stop import iteration_limit as _quality_iteration_limit
        _quality_limit = _quality_iteration_limit()
        if _quality_limit is not None:
            kwargs["max_iterations"] = _quality_limit
'''
REQUEST_ANCHOR='''                # Outbound-request surrogate chokepoint (#50959): the messages
'''
REQUEST_HOOK='''                # A premature v2 review stop must continue with real reads.
                from quality_review_stop import apply_request as _quality_review_request
                api_kwargs = _quality_review_request(
                    agent, api_kwargs, messages,
                    min(agent.max_iterations - api_call_count, agent.iteration_budget.remaining),
                )
'''


def adapt_loop(source):
    if source.count(LOOP_ANCHOR)!=1 or '_quality_review_guard' in source:
        raise ValueError('pinned Hermes finalization seam changed')
    return source.replace(LOOP_ANCHOR,LOOP_HOOK+LOOP_ANCHOR)


def adapt_acp(source):
    if source.count(STREAM_ANCHOR)!=1 or 'quality_review_stop' in source:
        raise ValueError('pinned Hermes ACP streaming seam changed')
    return source.replace(STREAM_ANCHOR,STREAM_HOOK)


def adapt_session(source):
    if source.count(SESSION_ANCHOR)!=1 or '_quality_iteration_limit' in source:
        raise ValueError('pinned Hermes ACP agent factory changed')
    return source.replace(SESSION_ANCHOR,SESSION_HOOK+SESSION_ANCHOR)


def adapt_request(source):
    if source.count(REQUEST_ANCHOR)!=1 or '_quality_review_request' in source:
        raise ValueError('pinned Hermes outbound request seam changed')
    return source.replace(REQUEST_ANCHOR,REQUEST_HOOK+REQUEST_ANCHOR)


if __name__=='__main__':
    loop=Path('/opt/hermes/agent/conversation_loop.py')
    acp=Path('/opt/hermes/acp_adapter/server.py')
    session=Path('/opt/hermes/acp_adapter/session.py')
    # Prepare/compile both before any write; no partial install on source drift.
    changed=[(loop,adapt_request(adapt_loop(loop.read_text()))),(acp,adapt_acp(acp.read_text())),
        (session,adapt_session(session.read_text()))]
    for path,source in changed:compile(source,str(path),'exec')
    for path,source in changed:path.write_text(source)
