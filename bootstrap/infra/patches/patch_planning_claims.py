"""Fail closed at native claim, not merely in prompts/tool schemas."""
import ast
from pathlib import Path


def apply(source):
    marker = '    from planning_flow import claim_allowed as planning_claim_allowed\n'
    if source.count(marker) == 2:
        return source
    if marker in source:
        raise ValueError('partial planning claim patch')
    tree = ast.parse(source)
    offsets = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ('claim_task', 'claim_review_task'):
            first = node.body[0]
            offsets.append(first.end_lineno if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) else first.lineno - 1)
    if len(offsets) != 2:
        raise ValueError('native claim functions not found')
    lines = source.splitlines(keepends=True)
    for offset in sorted(offsets, reverse=True):
        lines.insert(offset, marker + '    if not planning_claim_allowed(conn, task_id):\n        return None\n')
    return ''.join(lines)


if __name__ == '__main__':
    path = Path('/opt/hermes/hermes_cli/kanban_db.py')
    path.write_text(apply(path.read_text()))
