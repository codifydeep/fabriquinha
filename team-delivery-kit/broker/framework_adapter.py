"""Pure, fail-closed scaffolding adaptation; never mutates an author workspace.

Only undecorated, zero-argument module test functions and UNUSED pytest imports
are supported. Framework behavior (including module marks) requires diagnosis,
not silent deletion. Receipts are transform evidence, not Red or approval.
"""
import ast
import copy
import hashlib
import re

from surgical_test_edit import _discoverable, _tests


def adapt(source, expected_sha256):
    if (not isinstance(source, bytes) or not 0 < len(source) <= 32768
            or not re.fullmatch('[0-9a-f]{64}', str(expected_sha256))
            or hashlib.sha256(source).hexdigest() != expected_sha256):
        raise ValueError('adapter_source_drift')
    try:
        original = ast.parse(source)
    except (SyntaxError, UnicodeError):
        raise ValueError('adapter_invalid_syntax') from None
    tests = [n for n in original.body if isinstance(n, ast.FunctionDef)
             and n.name.startswith('test_')]
    all_tests = [n for n in ast.walk(original)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name.startswith('test_')]
    if not tests or len(tests) != len(all_tests):
        raise ValueError('adapter_test_shape_unsupported')
    if len({n.name for n in tests}) != len(tests):
        raise ValueError('adapter_duplicate_test_names')
    for test in tests:
        args = test.args
        if (test.decorator_list or test.returns or test.type_comment
                or getattr(test, 'type_params', []) or args.args or args.posonlyargs
                or args.kwonlyargs or args.vararg or args.kwarg or args.defaults):
            raise ValueError('adapter_test_signature_unsupported')
    names = {n.id for n in ast.walk(original) if isinstance(n, ast.Name)}
    definitions = {n.name for n in ast.walk(original)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    bindings = names | definitions | {a.arg for n in ast.walk(original)
                                      if isinstance(n, ast.arguments)
                                      for a in n.args + n.posonlyargs + n.kwonlyargs}
    bindings |= {a.asname or a.name.split('.')[0] for n in ast.walk(original)
                 if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    if bindings & {'unittest', 'DeliveryAdaptedTests', 'self'}:
        raise ValueError('adapter_binding_collision')
    if names & ({n.name for n in tests} | {'globals', 'locals', 'vars', 'eval', 'exec', 'super', '__class__'}):
        raise ValueError('adapter_binding_sensitive')
    if any(isinstance(n, ast.Attribute) and n.attr in {
            '_getframe', 'currentframe', 'f_locals', '__code__', '__globals__',
            '__qualname__', 'skip', 'skipif', 'skipIf', 'skipUnless', 'skipTest', 'SkipTest'}
           for n in ast.walk(original)):
        raise ValueError('adapter_framework_behavior')
    removed = 0
    retained = []
    for node in original.body:
        if node in tests:
            continue
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('pytest', '_pytest'):
            raise ValueError('adapter_framework_behavior')
        if isinstance(node, ast.Import):
            keep = []
            for alias in node.names:
                if alias.name.split('.')[0] in ('pytest', '_pytest'):
                    if (alias.asname or alias.name.split('.')[0]) in names:
                        raise ValueError('adapter_framework_behavior')
                    removed += 1
                else:
                    keep.append(alias)
            if not keep:
                continue
            node = copy.deepcopy(node)
            node.names = keep
        retained.append(copy.deepcopy(node))
    methods = copy.deepcopy(tests)
    for method in methods:
        method.args.args = [ast.arg(arg='self')]
    wrapper = ast.ClassDef(name='DeliveryAdaptedTests', bases=[
        ast.Attribute(value=ast.Name(id='unittest', ctx=ast.Load()), attr='TestCase', ctx=ast.Load())],
        keywords=[], body=methods, decorator_list=[])
    if hasattr(original, 'type_params'):
        wrapper.type_params = []
    # Preserve docstring and future-import positions; insert only after them.
    index = 0
    if retained and isinstance(retained[0], ast.Expr) and isinstance(retained[0].value, ast.Constant) and isinstance(retained[0].value.value, str):
        index = 1
    while index < len(retained) and isinstance(retained[index], ast.ImportFrom) and retained[index].module == '__future__':
        index += 1
    retained.insert(index, ast.Import(names=[ast.alias(name='unittest')]))
    tree = ast.fix_missing_locations(ast.Module(body=retained + [wrapper], type_ignores=[]))
    result = (ast.unparse(tree) + '\n').encode()
    parsed = ast.parse(result)
    if len(result) > 32768 or _tests(original) != _tests(parsed):
        raise ValueError('adapter_preservation_failed')
    _discoverable(parsed)
    return result, dict(operation='deterministic_unittest_scaffolding_v1',
        original_sha256=expected_sha256, adapted_sha256=hashlib.sha256(result).hexdigest(),
        test_count=len(tests), test_bodies_preserved=True,
        removed_unused_framework_imports=removed, discovery_validated=True,
        delivery_approval=False, red_evidence=False)
