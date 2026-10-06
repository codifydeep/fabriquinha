"""Structured Hermes failures cannot become successful ACP end-turn replies."""


def require_success(result, *, interrupted=False):
    if not isinstance(result,dict):raise RuntimeError('hermes_result_invalid')
    if result.get('failed') is True or (result.get('completed') is False and not interrupted):
        reason=result.get('failure_reason')
        safe={'billing','rate_limit','timeout','request_timeout','server_error','agent_exception'}
        category=reason if isinstance(reason,str) and reason in safe else 'execution_error'
        raise RuntimeError('hermes_run_failed:'+category)
    return result
