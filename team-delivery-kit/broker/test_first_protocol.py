"""Controller-owned test-first artifacts; no agent-supplied test commands.

The Red tree is the pinned Git base plus new test files only. It is never
reconstructed from a completed implementation. The caller must freeze this
tree before granting any product-code edit for the same issue.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from portable_contract import MAX_FILE_BYTES, safe_path, validate
from test_runner_policy import unacceptable_output

NEW_TEST_MAX_BYTES = 32768


class SnapshotRejection(ValueError):
    def __init__(self, category, message, files=None):
        super().__init__(message)
        self.receipt={'kind':'rejected_snapshot','category':category,'files':files or {}}


def snapshot_rejection_error(receipt):
    """Only fixed controller categories can trigger a corrective handoff."""
    if not isinstance(receipt,dict) or receipt.get('kind')!='rejected_snapshot':
        return 'test-first snapshot rejected'
    return {'test_path_mismatch':'test-first test path mismatch',
            'new_test_too_large':'test-first NEW test exceeds worker snapshot limit',
            'empty_new_test':'test-first NEW test is empty',
            'new_test_no_methods':'test-first NEW test has no executable test methods',
            'new_test_syntax_error':'test-first NEW test syntax is invalid',
            'new_test_framework_mismatch':'test-first NEW test imports an unpinned test framework',
            'source_layout':'test-first source layout rejected'}.get(
                receipt.get('category'),'test-first snapshot rejected')


def _regular(root, name):
    path = root / name
    if (path.is_symlink() or any(parent.is_symlink() for parent in
            list(path.parents)[:len(Path(name).parts) - 1]) or not path.is_file()):
        raise ValueError('non-regular test-first file: ' + name)
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('test-first file too large: ' + name)
    return data


def _test_methods(name, data):
    if name.endswith('.py'):
        facts = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
        try:
            tree = ast.parse(data, filename=name)
        except SyntaxError as error:
            facts[name].update(line=error.lineno, offset=error.offset)
            raise SnapshotRejection('new_test_syntax_error', 'new test syntax is invalid: ' + name, facts) from None
        methods = [node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name.startswith('test_')]
        if not methods:
            raise SnapshotRejection('new_test_no_methods', 'new test file has no test methods: ' + name, facts)
        return methods
    if name.endswith(('.js', '.mjs')) and re.search(rb'\b(?:test|it)\s*\(', data):
        return ['node_test']
    raise ValueError('new test file has no recognizable tests: ' + name)


def validate_test_framework(name, data, command):
    """Unittest-only artifacts cannot introduce pytest as a second framework.

    This is an early compatibility check, not a dependency resolver or sandbox.
    Arbitrary import/runtime failures still require executed-suite evidence.
    Projects with other pinned runners are unaffected.
    """
    if not name.endswith('.py') or command[1:3] != ['-m', 'unittest']:
        return
    tree = ast.parse(data, filename=name)  # Syntax has already been checked.
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module.split('.')[0])
    if any(module in ('pytest', '_pytest') for module in modules):
        raise SnapshotRejection('new_test_framework_mismatch',
            'test-first NEW test imports an unpinned test framework',
            {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}})


def prepare_red(base, workspace, frozen, contract, *, resume=False):
    """Copy verified base and only new tests into a controller volume."""
    base, workspace, frozen = map(Path, (base, workspace, frozen))
    contract = validate(contract)
    base_manifest = json.loads(_regular(base, 'manifest.json'))
    if set(base_manifest) != {'base_sha', 'files'}:
        raise ValueError('invalid base manifest')
    expected = base_manifest['files']
    if (not isinstance(expected, dict)
            or expected.get('contract.json') != hashlib.sha256(_regular(base, 'contract.json')).hexdigest()):
        raise ValueError('base contract hash mismatch')
    existing = set(expected) - {'contract.json'}
    new_tests = set(contract['test_files']) - existing
    if not new_tests or not new_tests <= set(contract['editable_files']):
        raise ValueError('no editable new tests declared')
    if any(name in existing for name in new_tests):
        raise ValueError('new test overlaps base')
    actual = {str(path.relative_to(workspace)) for path in workspace.rglob('*')
              if path.is_file() or path.is_symlink()}
    marker = '.delivery-kit-base.json'
    if marker in actual:
        expected_marker = {
            'base_sha': base_manifest['base_sha'],
            'manifest_sha256': hashlib.sha256(_regular(base, 'manifest.json')).hexdigest(),
        }
        if json.loads(_regular(workspace, marker)) != expected_marker:
            raise ValueError('test-first workspace base marker mismatch')
        actual.remove(marker)
    if actual != existing | new_tests:
        extra=actual-(existing|new_tests)
        path_mismatch=(existing<=actual and bool(new_tests-actual) and bool(extra)
            and all(name.endswith('.py') and any(name.startswith(root.rstrip('/')+'/')
                for root in contract['test_roots']) for name in extra))
        raise SnapshotRejection('test_path_mismatch' if path_mismatch else 'source_layout',
                                'test-first workspace changed code or omitted tests')
    contents = {}
    test_hashes = {}
    test_methods = {}
    for name in sorted(existing | new_tests):
        data = _regular(workspace, name)
        # Match the final snapshot/worker-file gate BEFORE accepting Red or
        # an immutable test review. Existing controller base files retain their
        # separate portable-contract bound; new worker tests cannot exceed32KiB.
        if name in new_tests and len(data)>NEW_TEST_MAX_BYTES:
            raise SnapshotRejection('new_test_too_large','new test exceeds worker snapshot limit: ' + name,
                {name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'maximum_bytes':NEW_TEST_MAX_BYTES}})
        if name in existing:
            if hashlib.sha256(data).hexdigest() != expected[name] or data != _regular(base, name):
                raise ValueError('base file changed before Red: ' + name)
        else:
            if not data:
                raise SnapshotRejection('empty_new_test', 'new test is empty: ' + name,
                    {name: {'bytes': 0, 'sha256': hashlib.sha256(data).hexdigest()}})
            test_methods[name] = _test_methods(name, data)
            validate_test_framework(name, data, contract['test_command'])
            test_hashes[name] = hashlib.sha256(data).hexdigest()
        contents[name] = data
    all_files = {}
    actual_frozen = {str(path.relative_to(frozen)) for path in frozen.rglob('*')
                     if path.is_file() or path.is_symlink()}
    if actual_frozen and not resume:
        raise ValueError('test-first destination is not empty')
    if not actual_frozen <= set(contents) | {'manifest.json'}:
        raise ValueError('unexpected test-first snapshot entry')
    for name, data in contents.items():
        destination = frozen / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            if not resume or _regular(frozen, name) != data:
                raise ValueError('test-first snapshot differs from source')
        else:
            with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), 'wb') as stream:
                stream.write(data)
        all_files[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    manifest_bytes = json.dumps({'files': all_files}, sort_keys=True,
                                separators=(',', ':')).encode()
    manifest_path = frozen / 'manifest.json'
    if manifest_path.exists() or manifest_path.is_symlink():
        if not resume or _regular(frozen, 'manifest.json') != manifest_bytes:
            raise ValueError('test-first manifest changed')
    else:
        with os.fdopen(os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), 'wb') as stream:
            stream.write(manifest_bytes)
    return {'base_sha': base_manifest['base_sha'],
            'base_manifest_sha256': hashlib.sha256(_regular(base, 'manifest.json')).hexdigest(),
            'baseline_test_sha256': {name: expected[name] for name in contract['test_files'] if name in existing},
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'test_sha256': test_hashes, 'test_methods': test_methods,
            'command': contract['test_command'], 'test_roots': contract['test_roots'],
            'test_count_pattern': contract['test_count_pattern'],
            'test_image': contract['test_image']}


def save_red_rejection(directory, issue_id, task_id, exit_code, output, prepared, reason):
    """Durable diagnostic, explicitly not an accepted Red receipt."""
    import uuid
    for identity in (issue_id, task_id):
        if str(uuid.UUID(identity)) != identity:
            raise ValueError('invalid Red incident identity')
    record = {'kind': 'rejected_red', 'issue_id': issue_id, 'task_id': task_id,
              'manifest_sha256': prepared['manifest_sha256'],
              'test_sha256': prepared['test_sha256'], 'command': prepared['command'],
              'test_methods': prepared.get('test_methods', {}),
              'exit_code': exit_code, 'reason': reason,
              'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
              'output_excerpt': output[-6000:], 'output_truncated': len(output) > 6000}
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = directory / (task_id + '.json')
    if destination.exists():
        prior = json.loads(destination.read_text())
        for key in ('kind', 'issue_id', 'task_id', 'manifest_sha256', 'test_sha256', 'command'):
            if prior.get(key) != record[key]:
                raise ValueError('Red incident identity drift')
        return prior
    with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(record, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    return record


def assess_red(exit_code, output, prepared):
    """Accept a real failed test, not a missing interpreter or collection error."""
    if (type(exit_code) is not int or exit_code != 1 or not isinstance(output, str)
            or unacceptable_output(output)):
        raise ValueError('Red must be an executed failing test suite')
    if not re.search(prepared['test_count_pattern'], output):
        raise ValueError('Red test count missing')
    if prepared['command'][0] == 'python3':
        failing = re.findall(r'(?m)^(?:FAIL|ERROR): (test_[A-Za-z0-9_]+) \(([^\n]+)\)', output)
        if not any(method in prepared['test_methods'].get(name, [])
                   and Path(name).stem in module
                   for method, module in failing for name in prepared['test_methods']):
            raise ValueError('Red did not fail in a new test method')
        if not re.search(r'(?m)^FAILED \((?:failures|errors)=', output):
            raise ValueError('Red failure summary missing')
    elif not re.search(r'(?m)^not ok \d+', output):
        raise ValueError('Red did not fail in an executed test')
    else:
        raise ValueError('unqualified Red runner')
    receipt = {'exit_code': exit_code, 'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
            'manifest_sha256': prepared['manifest_sha256'],
            'test_sha256': prepared['test_sha256'], 'command': prepared['command']}
    # Only new, fully bound captures receive this evidence version. Never infer
    # missing historical metadata from a later snapshot or an agent's prose.
    if 'base_manifest_sha256' in prepared and 'baseline_test_sha256' in prepared:
        counts = re.findall(prepared['test_count_pattern'], output)
        if len(counts) != 1 or not isinstance(counts[0], str) or not counts[0].isdigit():
            raise ValueError('unambiguous executed Red count required')
        receipt.update(evidence_version=2, test_count=int(counts[0]),
                       base_manifest_sha256=prepared['base_manifest_sha256'],
                       baseline_test_sha256=prepared['baseline_test_sha256'],
                       test_image=prepared['test_image'])
    return receipt


def verify_green_tests(delivery, red):
    """The reviewed delivery must contain the exact tests frozen before Red."""
    delivery = Path(delivery)
    for name, digest in red['test_sha256'].items():
        safe_path(name)
        data = _regular(delivery, name)
        if len(data)>NEW_TEST_MAX_BYTES:
            raise ValueError('new test exceeds worker snapshot limit: ' + name)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('test changed after controller Red: ' + name)
    return True
