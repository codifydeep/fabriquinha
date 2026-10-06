"""Hash-bound AST diagnosis of one supported prerequisite; never executes code."""
import ast
import hashlib
import re


def diagnose(source, expected_sha256):
    if (not isinstance(source, bytes) or not 0 < len(source) <= 32768
            or not re.fullmatch('[0-9a-f]{64}', str(expected_sha256))
            or hashlib.sha256(source).hexdigest() != expected_sha256):
        raise ValueError('mark_diagnosis_source_drift')
    tree = ast.parse(source)
    marks = [n for n in tree.body if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id == 'pytestmark']
    if len(marks) != 1:
        raise ValueError('mark_diagnosis_unsupported')
    call = marks[0].value
    expected_func = ast.parse('pytest.mark.skipif', mode='eval').body
    if (not isinstance(call, ast.Call)
            or ast.dump(call.func) != ast.dump(expected_func) or len(call.args) != 1
            or any(k.arg != 'reason' or not isinstance(k.value, ast.Constant)
                   or not isinstance(k.value.value, str) for k in call.keywords)):
        raise ValueError('mark_diagnosis_unsupported')
    condition = call.args[0]
    if not isinstance(condition, ast.UnaryOp) or not isinstance(condition.op, ast.Not):
        raise ValueError('mark_diagnosis_unsupported')
    invoke = condition.operand
    if (not isinstance(invoke, ast.Call) or not isinstance(invoke.func, ast.Name)
            or invoke.args or invoke.keywords):
        raise ValueError('mark_diagnosis_unsupported')
    name = invoke.func.id
    helpers = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    expected_body = ast.parse('def available():\n    return shutil.which("node") is not None\n').body[0]
    if (len(helpers) != 1 or not isinstance(helpers[0], ast.FunctionDef)
            or helpers[0].decorator_list or helpers[0].returns
            or ast.dump(helpers[0].args) != ast.dump(expected_body.args)
            or [ast.dump(n) for n in helpers[0].body] != [ast.dump(n) for n in expected_body.body]):
        raise ValueError('mark_diagnosis_unsupported')
    for module in ('shutil', 'pytest'):
        bindings = [a for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                    for a in n.names if (a.asname or a.name.split('.')[0]) == module]
        top_import = [a for n in tree.body if isinstance(n, ast.Import)
                      for a in n.names if a.name == module and a.asname is None]
        if len(bindings) != 1 or len(top_import) != 1:
            raise ValueError('mark_diagnosis_binding_drift')
    sensitive = {'shutil', 'pytest', name, 'pytestmark'}
    stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
              and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id in sensitive]
    if len(stores) != 1 or stores[0] is not marks[0].targets[0]:
        raise ValueError('mark_diagnosis_binding_drift')
    if any(isinstance(n, (ast.ClassDef, ast.AsyncFunctionDef)) and n.name in sensitive
           or isinstance(n, ast.FunctionDef) and n.name in sensitive and n is not helpers[0]
           or isinstance(n, ast.arg) and n.arg in sensitive for n in ast.walk(tree)):
        raise ValueError('mark_diagnosis_binding_drift')
    return dict(operation='static_node_prerequisite_diagnosis_v1',
                source_sha256=expected_sha256, predicate='skip_when_node_absent',
                dependency='node', executed_source=False, repository_modified=False,
                delivery_approval=False, red_evidence=False)


def adapt_required_node(source, expected_sha256):
    """Produce a candidate only: a mandatory prerequisite replaces NEW skipping.

    This does not authorize applying it to an author workspace. The controller
    must separately bind independent CTO sponsorship, immutable input, review
    and actual Red. No approval can be supplied as an argument by a worker.
    """
    diagnose(source, expected_sha256)
    try:
        from framework_adapter import adapt
    except ImportError:
        from broker.framework_adapter import adapt
    from surgical_test_edit import _tests, _discoverable
    original = ast.parse(source)
    tree = ast.parse(source)
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'pytestmark')]
    intermediate = (ast.unparse(tree) + '\n').encode()
    wrapped, _ = adapt(intermediate, hashlib.sha256(intermediate).hexdigest())
    tree = ast.parse(wrapped)
    wrapper = tree.body[-1]
    prerequisite = ast.parse('''@classmethod
def setUpClass(cls):
    if shutil.which("node") is None:
        raise RuntimeError("required node runtime unavailable")
''').body[0]
    # An untrusted existing binding must not hide our explicit preflight failure.
    if any(isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
           and n.id == 'RuntimeError' or isinstance(n, (ast.FunctionDef, ast.ClassDef))
           and n.name == 'RuntimeError' or isinstance(n, (ast.Import, ast.ImportFrom))
           and any((a.asname or a.name.split('.')[0]) == 'RuntimeError' for a in n.names)
           for n in ast.walk(original)):
        raise ValueError('mark_adapter_preflight_binding_drift')
    wrapper.body.insert(0, prerequisite)
    result = (ast.unparse(ast.fix_missing_locations(tree)) + '\n').encode()
    parsed = ast.parse(result)
    if len(result) > 32768 or _tests(original) != _tests(parsed):
        raise ValueError('mark_adapter_preservation_failed')
    _discoverable(parsed)
    return result, dict(operation='required_node_unittest_scaffolding_v1',
        original_sha256=expected_sha256, adapted_sha256=hashlib.sha256(result).hexdigest(),
        test_bodies_preserved=True, test_count=sum(_tests(parsed).values()),
        mandatory_node_preflight=True, removed_new_conditional_mark=True,
        delivery_approval=False, red_evidence=False)
