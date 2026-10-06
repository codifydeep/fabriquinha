"""Pin the actual ACP AIAgent constructor to the 40-iteration contract.

ACP does not forward agent.max_turns from config. Changing only config.yaml
therefore cannot bound this pinned runtime. Fail closed if its constructor drifts.
"""
import ast
from pathlib import Path

ANCHOR = '            "model": model or default_model,\n'
REPLACEMENT = ANCHOR + '            "max_iterations": 40,\n'


def adapt(source):
    if source.count(ANCHOR) != 1 or REPLACEMENT in source:
        raise ValueError('pinned ACP agent constructor changed')
    tree = ast.parse(source)
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and node.name == '_make_agent']
    if len(methods) != 1:
        raise ValueError('pinned ACP agent factory changed')
    dictionaries = [node.value for node in methods[0].body
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id == 'kwargs' for target in node.targets)]
    if len(dictionaries) != 1 or not isinstance(dictionaries[0], ast.Dict):
        raise ValueError('pinned ACP kwargs changed')
    keys = [key.value if isinstance(key, ast.Constant) else None for key in dictionaries[0].keys]
    if 'model' not in keys or 'max_iterations' in keys:
        raise ValueError('pinned ACP kwargs limit drift')
    result = source.replace(ANCHOR, REPLACEMENT)
    compile(result, '<bounded-acp-session>', 'exec')
    return result


if __name__ == '__main__':
    target = Path('/opt/hermes/acp_adapter/session.py')
    if target.is_symlink():
        raise ValueError('unexpected ACP source symlink')
    target.write_text(adapt(target.read_text()))
