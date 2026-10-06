"""Inspect a failed tests-only snapshot without accepting Red or reviving a task.

Run only in a disposable offline sandbox with snapshot and base mounted read-only.
The command/image originate in the controller-owned base, never agent arguments.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from portable_contract import validate
try:
    from test_first_protocol import prepare_red, assess_red
    from suite_failure import evidence
except ImportError:
    from broker.test_first_protocol import prepare_red, assess_red
    from broker.suite_failure import evidence
from test_runner_policy import validate_argv


def prepare_snapshot(snapshot, base, frozen, *, resume=False):
    snapshot, base = Path(snapshot), Path(base)
    raw = (snapshot / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if set(manifest) != {'files'} or not isinstance(manifest['files'], dict):
        raise ValueError('invalid diagnostic manifest')
    contract = validate(json.loads((base / 'contract.json').read_bytes()))
    # No extra files, symlinks, or modified bytes may hide outside the manifest.
    actual = {str(p.relative_to(snapshot)) for p in snapshot.rglob('*')
              if p.is_file() or p.is_symlink()}
    if actual != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('diagnostic snapshot file set mismatch')
    for name, record in manifest['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('invalid diagnostic path')
        source = snapshot / path
        if source.is_symlink() or any(p.is_symlink() for p in list(source.parents)[:len(path.parts)-1]):
            raise ValueError('diagnostic symlink forbidden')
        data = source.read_bytes()
        if record != {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            raise ValueError('diagnostic snapshot hash mismatch')
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / 'workspace'
        workspace.mkdir()
        # prepare_red checks unchanged baseline, new tests, syntax and framework.
        # Omit only the snapshot's controller manifest, not any artifact file.
        for name in manifest['files']:
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((snapshot / name).read_bytes())
        return prepare_red(base, workspace, frozen, contract, resume=resume)


def inspect(snapshot, base, *, run=subprocess.run):
    snapshot, base = Path(snapshot), Path(base)
    raw = (snapshot / 'manifest.json').read_bytes()
    with tempfile.TemporaryDirectory() as temporary:
        frozen = Path(temporary) / 'frozen'
        frozen.mkdir()
        prepared = prepare_snapshot(snapshot, base, frozen)
    validate_argv(prepared['command'], prepared['test_roots'])
    result = run(prepared['command'], cwd=snapshot, capture_output=True,
                 text=True, timeout=60)
    output = result.stdout + result.stderr
    candidate = False
    try:
        assess_red(result.returncode, output, prepared)
        candidate = True
    except ValueError:
        pass
    failed = evidence(result.returncode, output, 'diagnostic', 'diagnostic') if result.returncode else None
    # Never export test output, paths from traceback, commands, or assertion text.
    return dict(operation='failed_pre_red_snapshot_diagnostic_v1',
                diagnostic_only=True, delivery_approved=False,
                native_task_completed=False, red_captured=False, model_calls=0,
                manifest_sha256=hashlib.sha256(raw).hexdigest(),
                baseline_unchanged=True, test_sha256=prepared['test_sha256'],
                exit_code=result.returncode, red_candidate=candidate,
                failure_category=failed['category'] if failed else 'suite_passed',
                tests_executed=failed['tests_executed'] if failed else None,
                failure_kinds=sorted({f['kind'] for f in failed['failures']}) if failed else [],
                exception_types=failed['exception_types'] if failed else [],
                output_sha256=hashlib.sha256(output.encode()).hexdigest())


if __name__ == '__main__':
    print(json.dumps(inspect('/delivery', '/base'), sort_keys=True))
