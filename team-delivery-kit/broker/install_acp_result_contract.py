"""Fail-closed adapter patch: propagate structured errors, never scan prose."""
import ast
from pathlib import Path

RESULT='        final_response = result.get("final_response", "")\n'
REPLACEMENT='''        from acp_result_contract import require_success
        try:
            require_success(result, interrupted=bool(result.get("interrupted")) or
                            bool(state.cancel_event and state.cancel_event.is_set()))
        except RuntimeError:
            with state.runtime_lock:
                state.is_running = False
                state.current_prompt_text = ""
            raise
'''+RESULT
EXCEPTION='                return {"final_response": f"Error: {e}", "messages": state.history}\n'
SAFE_EXCEPTION='''                return {"final_response": "", "messages": state.history,
                        "failed": True, "completed": False, "failure_reason": "agent_exception"}
'''
EXECUTOR='''            logger.exception("Executor error for session %s", session_id)
            with state.runtime_lock:
                state.is_running = False
                state.current_prompt_text = ""
            return PromptResponse(stop_reason="end_turn")
'''
SAFE_EXECUTOR=EXECUTOR.replace('return PromptResponse(stop_reason="end_turn")',
                             'raise RuntimeError("hermes_executor_failed") from None')


def adapt(source):
    ast.parse(source)
    if 'from acp_result_contract import require_success' in source:
        raise ValueError('ACP result contract already installed')
    for anchor in (RESULT,EXCEPTION,EXECUTOR):
        if source.count(anchor)!=1:raise ValueError('pinned ACP result path changed')
    changed=source.replace(RESULT,REPLACEMENT).replace(EXCEPTION,SAFE_EXCEPTION).replace(EXECUTOR,SAFE_EXECUTOR)
    compile(changed,'<acp-structured-failure-contract>','exec')
    return changed


if __name__=='__main__':
    path=Path('/opt/hermes/acp_adapter/server.py')
    if path.is_symlink():raise ValueError('unexpected ACP source symlink')
    path.write_text(adapt(path.read_text()))
