"""Pinned adaptation retaining normal finalizer persistence and cleanup."""
import ast
from pathlib import Path

ANCHOR = '    if continuation_budget_exhausted:\n'
REPLACEMENT = '''    from iteration_budget_contract import bounded_failure
    delivery_controller_budget_exhausted = bounded_failure(
        os.environ.get("DELIVERY_EXECUTION_MODE"), budget_fallback_eligible)
    if delivery_controller_budget_exhausted:
        final_response = ""
        failed = True
        _turn_exit_reason = "iteration_budget_exhausted"
        iteration_limit_fallback = True
    elif continuation_budget_exhausted:
'''
RETURN = '    return result\n'
STAMP = '''    if delivery_controller_budget_exhausted:
        result["failed"] = True
        result["completed"] = False
        result["failure_reason"] = "iteration_budget_exhausted"
'''+RETURN


def adapt(source):
    ast.parse(source)
    if 'delivery_controller_budget_exhausted' in source:
        raise ValueError('iteration budget contract already installed')
    if source.count(ANCHOR)!=1 or source.count(RETURN)!=1:
        raise ValueError('pinned iteration finalizer changed')
    changed=source.replace(ANCHOR,REPLACEMENT).replace(RETURN,STAMP)
    compile(changed,'<iteration-budget-contract>','exec')
    return changed


if __name__=='__main__':
    path=Path('/opt/hermes/agent/turn_finalizer.py')
    if path.is_symlink():raise ValueError('unexpected finalizer symlink')
    path.write_text(adapt(path.read_text()))
