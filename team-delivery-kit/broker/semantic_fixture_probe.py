"""Bounded Python string experiments; never execute repository expressions."""
import ast
import json
import os
from pathlib import Path

from assertion_witness import extract


def calculate(root, hashes, output):
    proof = extract(root, hashes, output)
    facts = []
    contradictions = []
    for witness in proof['witnesses']:
        qualified = witness['qualified_name']
        paths = [p for p in hashes if qualified.startswith(p[:-3].replace('/', '.') + '.')]
        if len(paths) != 1:
            continue
        tree = ast.parse((root / paths[0]).read_bytes())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name == qualified.split('.')[-1]]
        if len(methods) != 1:
            continue
        titles = sorted(set(witness['observed'] + witness['expected']))
        for node in ast.walk(methods[0]):
            if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                    or node.func.attr != 'search' or not node.args
                    or not isinstance(node.args[0], ast.Constant)
                    or not isinstance(node.args[0].value, str) or len(node.args[0].value) > 80):
                continue
            query = node.args[0].value
            for title in titles:
                fact = {'test': qualified, 'file': paths[0], 'query_line': node.lineno,
                              'query': query, 'title': title,
                              'casefold_substring': query.strip().casefold() in title.casefold()}
                facts.append(fact)
                parent = parents.get(node)
                if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                        and parent.func.attr == 'assertEqual' and len(parent.args) == 2
                        and parent.args[0] is node and isinstance(parent.args[1], ast.List)
                        and all(isinstance(item, ast.Constant) and isinstance(item.value, str)
                                for item in parent.args[1].elts)):
                    expected = [item.value for item in parent.args[1].elts]
                    # Comparing another fixture (German vs Greek) is not a contradiction.
                    if not expected or expected == [title]:
                        asserted = bool(expected)
                        if asserted is not fact['casefold_substring']:
                            contradictions.append({**fact, 'asserted_match': asserted})
            if len(facts) > 16:
                raise ValueError('split semantic experiment')
    return {**proof, 'operation': 'python_str_strip_casefold_substring_v1', 'facts': facts,
            'contradictions': contradictions,
            'status': 'experiment_only_not_green_or_approval'}


def calculate_scope(root, hashes, scope):
    """Recheck literal assertions in a NEW snapshot against controller-owned scope.

    No old failing output is interpreted as the new candidate's result. Scope
    identifies fixture/method pairs, not source line numbers or agent commands.
    Unsupported syntax cannot silently count as repaired.
    """
    proof = extract(root, hashes, '')  # verifies every declared test hash/manifest
    if not isinstance(scope, list) or not scope or len(scope) > 16:
        raise ValueError('bounded semantic scope required')
    facts, contradictions = [], []
    for item in scope:
        if set(item) != {'file', 'test', 'title'} or item['file'] not in hashes:
            raise ValueError('invalid semantic scope')
        module = item['file'][:-3].replace('/', '.')
        parts = item['test'].removeprefix(module + '.').split('.')
        if not item['test'].startswith(module + '.') or len(parts) != 2:
            raise ValueError('class/method scope required')
        tree = ast.parse((root / item['file']).read_bytes())
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == parts[0]]
        methods = [n for c in classes for n in c.body
                   if isinstance(n, ast.FunctionDef) and n.name == parts[1]]
        if len(classes) != 1 or len(methods) != 1:
            raise ValueError('semantic method removed or ambiguous')
        if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == 'create' and n.args and isinstance(n.args[0], ast.Constant)
                   and n.args[0].value == item['title'] for n in ast.walk(methods[0])):
            raise ValueError('recorded literal fixture changed or unsupported')
        found = 0
        for assertion in ast.walk(methods[0]):
            if (not isinstance(assertion, ast.Call) or not isinstance(assertion.func, ast.Attribute)
                    or assertion.func.attr != 'assertEqual' or len(assertion.args) != 2):
                continue
            call, expected = assertion.args
            if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute)
                    or call.func.attr != 'search' or len(call.args) != 1 or call.keywords
                    or not isinstance(call.args[0], ast.Constant)
                    or not isinstance(call.args[0].value, str) or len(call.args[0].value) > 80
                    or not isinstance(expected, ast.List)
                    or any(not isinstance(n, ast.Constant) or not isinstance(n.value, str) for n in expected.elts)):
                continue
            values = [n.value for n in expected.elts]
            if values and values != [item['title']]:
                continue  # assertion refers to another fixture
            query = call.args[0].value
            fact = {**item, 'query_line': call.lineno, 'query': query,
                    'casefold_substring': query.strip().casefold() in item['title'].casefold()}
            facts.append(fact)
            found += 1
            if bool(values) != fact['casefold_substring']:
                contradictions.append({**fact, 'asserted_match': bool(values)})
        if not found or len(facts) > 32:
            raise ValueError('unsupported or oversized semantic assertions')
    return {**proof, 'operation': 'python_str_strip_casefold_substring_v1', 'facts': facts,
            'contradictions': contradictions, 'status': 'experiment_only_not_green_or_approval'}


if __name__ == '__main__':
    root, hashes = Path('/delivery'), json.loads(os.environ['FROZEN_TEST_HASHES'])
    proof = (calculate_scope(root, hashes, json.loads(os.environ['SEMANTIC_SCOPE']))
             if 'SEMANTIC_SCOPE' in os.environ else calculate(root, hashes, json.loads(os.environ['SAVED_OUTPUT'])))
    print(json.dumps(proof, sort_keys=True), flush=True)
