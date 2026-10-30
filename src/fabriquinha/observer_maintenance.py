"""Structural qualifier for the shared browser-error observer repair.

This grants no write authority and is not an approval. A maintenance admission,
independent review, fresh full-suite execution and negative controls are still
required. Historical receipts retain their existing interpretation.
"""
import ast
import copy
from .test_revision import shape, candidate_diff

PROTOCOL = 'shared-browser-observer-1'


def observer_diff(before, after):
    """Accept only the precise duplicate-observer replacement, not arbitrary setup.

    Tests, assertions, flow, imports, discovery and all other helpers are fixed.
    The two helpers must belong to a direct AcceptanceTest subclass. The shared
    observer is installed by the controller's harness and cannot be modified here.
    """
    left, right = ast.parse(before), ast.parse(after)
    expected = copy.deepcopy(left)
    replacement = ast.parse('self._browser_errors', mode='eval').body
    assignment = ast.parse('errors = []').body[0]
    listeners = [ast.parse(line).body[0] for line in (
        "page.on('pageerror', lambda error: errors.append(str(error)))",
        "page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)")]
    aggregate = ast.parse('creator_errors + joiner_errors', mode='eval').body
    changes = []
    for cls in expected.body:
        if not isinstance(cls, ast.ClassDef): continue
        methods = {m.name:m for m in cls.body if isinstance(m, ast.FunctionDef)}
        if not {'open_home', 'full_room_pair'} <= methods.keys(): continue
        if len(cls.bases) != 1 or not isinstance(cls.bases[0], ast.Name) or cls.bases[0].id != 'AcceptanceTest':
            raise ValueError('direct AcceptanceTest subclass required')
        home = methods['open_home']
        fingerprints = [shape(n) for n in home.body]
        if any(fingerprints.count(shape(n)) != 1 for n in [assignment, *listeners]):
            raise ValueError('exact duplicate observer setup required')
        body = []
        for node in home.body:
            if shape(node) == shape(assignment):
                node.value = copy.deepcopy(replacement)
            elif any(shape(node) == shape(listener) for listener in listeners):
                continue
            body.append(node)
        home.body = body
        pair = methods['full_room_pair']; matches = 0
        for node in ast.walk(pair):
            if not isinstance(node, ast.Dict): continue
            for i, (key, value) in enumerate(zip(node.keys, node.values)):
                if isinstance(key, ast.Constant) and key.value == 'errors' and shape(value) == shape(aggregate):
                    node.values[i] = copy.deepcopy(replacement); matches += 1
        if matches != 1: raise ValueError('one copied observer aggregate required')
        changes.append(cls.name)
    if not changes or shape(expected) != shape(right):
        raise ValueError('only exact shared-observer helper substitution permitted')
    evidence = candidate_diff(before, after)
    return dict(protocol=PROTOCOL, classes=changes, **evidence)


def snapshot_diff(store, baseline, candidate, paths, tests_dir='tests'):
    """Check the whole candidate, not just a user-selected diff or case subset."""
    from pathlib import PurePosixPath
    left, right = store.manifest(baseline), store.manifest(candidate)
    if (not isinstance(paths, list) or not 1 <= len(paths) <= 2
            or any(not isinstance(p,str) for p in paths) or len(set(paths)) != len(paths)):
        raise ValueError('one or two exact observer fixture paths required')
    for path in paths:
        item = PurePosixPath(path)
        if (str(item) != path or item.parent.as_posix() != tests_dir
                or not item.name.startswith('acceptance_') or item.suffix != '.py'
                or path not in left or path not in right):
            raise ValueError('existing direct acceptance Python paths required')
    changed = {p for p in set(left) | set(right) if left.get(p) != right.get(p)}
    if changed != set(paths):
        raise ValueError('all and only the authorized fixtures must change')
    evidence = {}
    for path in paths:
        if left[path]['executable'] != right[path]['executable']:
            raise ValueError('file modes must remain unchanged')
        if left[path]['bytes'] + right[path]['bytes'] > 131072:
            raise ValueError('bounded fixture sources required')
        evidence[path] = observer_diff((store.tree(baseline)/path).read_text(),
                                      (store.tree(candidate)/path).read_text())
    if sum(len(item['diff']) for item in evidence.values()) > 24000:
        raise ValueError('bounded complete review diff required')
    return evidence
