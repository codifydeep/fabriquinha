"""Conservative AST witnesses for incompatible shared-capture expectations.

No source execution or approval. A witness assumes self.ids(key) denotes the
same shared observation across the cited tests; reviewers must verify that
assumption in the actual harness. Dynamic expressions are intentionally ignored.
"""
import ast


def inspect(source):
    tree = ast.parse(source)
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass

    def value(node):
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            return None

    def capture(node):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self'
                and node.func.attr == 'ids' and len(node.args) == 1 and not node.keywords
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            return node.args[0].value

    constraints = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef) or not method.name.startswith('test_'):
                continue
            aliases = {}
            for stmt in method.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            aliases[target.id] = capture(stmt.value)
                if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                    continue
                call = stmt.value
                if (not isinstance(call.func, ast.Attribute) or call.func.attr != 'assertEqual'
                        or not isinstance(call.func.value, ast.Name) or call.func.value.id != 'self'
                        or len(call.args) < 2):
                    continue
                left, right = call.args[:2]
                index = None
                if isinstance(left, ast.Subscript):
                    index = value(left.slice)
                    left = left.value
                key = aliases.get(left.id) if isinstance(left, ast.Name) else capture(left)
                expected = value(right)
                if key and (type(expected) is int or isinstance(expected, list)
                            and all(type(item) is int for item in expected)):
                    constraints.append({'capture': key, 'index': index, 'expected': expected,
                        'test': cls.name + '.' + method.name, 'line': stmt.lineno})
    witnesses = []
    for whole in constraints:
        if whole['index'] is not None or not isinstance(whole['expected'], list):
            continue
        for part in constraints:
            if part['capture'] != whole['capture'] or type(part['index']) is not int:
                continue
            try:
                implied = whole['expected'][part['index']]
            except IndexError:
                continue
            if implied != part['expected']:
                witnesses.append({'capture': whole['capture'], 'whole': whole,
                    'element': part, 'implied_element': implied,
                    'assumption': 'Both tests use the same shared observation; verify harness lifetime.'})
    return witnesses
