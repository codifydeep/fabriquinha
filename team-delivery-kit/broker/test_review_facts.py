"""Fixed offline facts about hash-bound tests; never a semantic approval."""
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

try:
    from test_size_inspection import inspect
except ImportError:
    from broker.test_size_inspection import inspect


def inventory(root, selection):
    measured = inspect(root, selection)
    result = {}
    for name, facts in measured['files'].items():
        text = (Path(root) / name).read_text()
        methods = {}
        if name.endswith('.py'):
            tree = ast.parse(text)
            def visit(nodes, prefix=''):
                for node in nodes:
                    if isinstance(node, ast.ClassDef):
                        visit(node.body, prefix + node.name + '.')
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                        symbol = prefix + node.name
                        if symbol in methods:
                            raise ValueError('duplicate test method')
                        assertions = [n for n in ast.walk(node) if isinstance(n, ast.Assert)
                            or isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr.startswith('assert')]
                        methods[symbol] = {'line': node.lineno, 'end_line': node.end_lineno,
                            'ast_sha256': hashlib.sha256(ast.dump(node).encode()).hexdigest(),
                            'assertions': [hashlib.sha256(ast.dump(n).encode()).hexdigest() for n in assertions]}
            visit(tree.body)
        result[name] = {**facts, 'language': 'python' if name.endswith('.py') else 'other',
                        'methods': methods, 'lines': text.splitlines()}
    return {'manifest_sha256': selection['manifest_sha256'], 'files': result}


def compare(candidate_root, previous_root, selection):
    candidate = inventory(candidate_root, selection['candidate'])
    previous = inventory(previous_root, selection['previous']) if selection.get('previous') else None
    files = {}
    for name, current in candidate['files'].items():
        old = previous['files'][name] if previous else {'methods': {}}
        before, after = old['methods'], current['methods']
        removed_assertions = {}
        for method in before.keys() & after.keys():
            lost = Counter(before[method]['assertions']) - Counter(after[method]['assertions'])
            if lost:
                removed_assertions[method] = dict(lost)
        files[name] = {'candidate_sha256': current['sha256'], 'previous_sha256': old.get('sha256'),
            'candidate_bytes': current['bytes'], 'previous_bytes': old.get('bytes'),
            'previous_methods': sorted(before), 'candidate_methods': sorted(after),
            'removed_methods': sorted(before.keys() - after.keys()),
            'added_methods': sorted(after.keys() - before.keys()),
            'changed_methods': sorted(m for m in before.keys() & after.keys()
                                      if before[m]['ast_sha256'] != after[m]['ast_sha256']),
            'previous_assertions': sum(len(m['assertions']) for m in before.values()),
            'candidate_assertions': sum(len(m['assertions']) for m in after.values()),
            'removed_assertion_ast': removed_assertions}
    return {'candidate': candidate, 'previous': previous,
            'summary': {'candidate_manifest': candidate['manifest_sha256'],
                        'previous_manifest': previous['manifest_sha256'] if previous else None,
                        'files': files,
                        'limitation': 'AST inventory is structural, not semantic equivalence or delivery approval.'}}


def validate_findings(decision, report):
    findings = decision.get('findings')
    approving = decision['action'] == 'approve_test_revision'
    if not isinstance(findings, list) or len(findings) > 3 or (approving and findings):
        raise ValueError('bounded findings required; approval cannot carry unresolved findings')
    if decision['action'] in ('reject_test_revision', 'request_test_revision') and not findings:
        raise ValueError('rejection requires concrete finding')
    fields = {'kind', 'tree', 'path', 'test', 'line', 'quote', 'expected', 'observed'}
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != fields:
            raise ValueError('exact finding fields required')
        disputing=(decision['action']=='request_review_reconsideration')
        if (finding['kind'] not in ('removed_method', 'removed_assertion', 'semantic_regression', 'missing_coverage', 'invalid_harness')
                and not (disputing and finding['kind']=='review_disagreement')):
            raise ValueError('unknown finding kind')
        tree = report.get(finding['tree']) if finding['tree'] in ('candidate', 'previous') else None
        file = (tree or {}).get('files', {}).get(finding['path'])
        if not file or finding['path'] not in report['summary']['files']:
            raise ValueError('finding artifact absent')
        symbol, line = finding['test'], finding['line']
        methods = file['methods']
        if (symbol != '__module__' and symbol not in methods or type(line) is not int
                or not 1 <= line <= len(file['lines'])):
            raise ValueError('finding test or line does not exist')
        if symbol != '__module__' and not methods[symbol]['line'] <= line <= methods[symbol]['end_line']:
            raise ValueError('finding line outside test')
        if any(not isinstance(finding[k], str) or not 1 <= len(finding[k]) <= 500
               for k in ('quote', 'expected', 'observed')):
            raise ValueError('bounded observed finding required')
        if not finding['quote'].strip() or finding['quote'] not in file['lines'][line - 1]:
            raise ValueError('finding quote not observed at exact line')
        diff = report['summary']['files'][finding['path']]
        if finding['kind'] == 'removed_method' and (
                finding['tree'] != 'previous' or symbol not in diff['removed_methods']):
            raise ValueError('claimed removed method contradicted by snapshot')
        if finding['kind'] == 'removed_assertion' and (
                finding['tree'] != 'previous' or symbol not in diff['removed_assertion_ast']
                or len(report['candidate']['files'][finding['path']]['methods'].get(symbol, {}).get('assertions', []))
                >= len(methods[symbol]['assertions'])):
            raise ValueError('claimed removed assertion contradicted by snapshot')
    return findings


if __name__ == '__main__':
    print(json.dumps(compare('/candidate', '/previous', json.loads(os.environ['COMPARISON_SELECTION']))))
