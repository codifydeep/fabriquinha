"""Fixed in-memory queue experiment. Never edits or approves an author delivery."""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import unittest

TEST = 'tests/test_incremental_u3.py'
ANCHOR = '          out.create_urls = getCalls();\n          return flush().then(function () {'
REPLACEMENT = '          out.create_urls = getCalls();\n          resolveNewest();\n          return flush().then(function () {'


def change(body):
    if not isinstance(body, str) or body.count(ANCHOR) != 1:
        raise ValueError('unique actual create observation required')
    return body.replace(ANCHOR, REPLACEMENT, 1)


def verify(root, expected_manifest, expected_test):
    raw = (root / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest:
        raise ValueError('exact snapshot manifest required')
    files = json.loads(raw)['files']
    for name, entry in files.items():
        if not isinstance(name, str) or name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('safe snapshot path required')
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError('regular snapshot files required')
        content = path.read_bytes()
        if entry != {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}:
            raise ValueError('snapshot file mismatch')
    if files[TEST]['sha256'] != expected_test:
        raise ValueError('exact author test required')
    return (root / TEST).read_bytes()


def run(root, expected_manifest, expected_test):
    original = verify(root, expected_manifest, expected_test)
    tree = ast.parse(original)
    drivers = [n for n in tree.body if isinstance(n, ast.Assign)
               and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id == 'DRIVER_BODY']
    if len(drivers) != 1:
        raise ValueError('one literal driver required')
    body = ast.literal_eval(drivers[0].value)
    changed = change(body)
    results = []
    for name, driver in (('baseline', body), ('settle_create_from_live_items', changed)):
        spec = importlib.util.spec_from_file_location('create_queue_' + name, root / TEST)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if module.DRIVER_BODY != body:
            raise ValueError('imported driver drift')
        module.DRIVER_BODY = driver  # in-memory experimental variant, never a file write
        stream = io.StringIO()
        case = module.IncrementalU3QueryMemoryTests
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
        cases = list(suite)
        result = unittest.TextTestRunner(stream=stream).run(suite)
        reports = [getattr(c, 'report', None) for c in cases]
        report = reports[0] if reports else None
        if (not isinstance(report, dict) or any(r != report for r in reports)
                or result.testsRun != 4 or result.errors or result.skipped):
            raise ValueError('four actual unmodified tests and one Node report required: '+
                             json.dumps({'tests': result.testsRun, 'errors': [c.id() for c, _ in result.errors],
                                         'report_present': isinstance(report, dict)}))
        observations = {}
        for key in ('rendered_after_poll', 'rendered_after_create', 'rendered_after_current_resolve'):
            values = report.get(key)
            if (not isinstance(values, list) or len(values) > 8
                    or any(not isinstance(v, str) or not re.fullmatch(r'[\w .-]{1,80}', v) for v in values)):
                raise ValueError('bounded synthetic title observations required')
            observations[key] = values
        results.append({'variant': name, 'tests': result.testsRun, 'errors': len(result.errors),
                        'failures': [case._testMethodName for case, _ in result.failures],
                        'driver_sha256': hashlib.sha256(driver.encode()).hexdigest(),
                        'output_sha256': hashlib.sha256(stream.getvalue().encode()).hexdigest(),
                        'observations': observations})
    if (root / TEST).read_bytes() != original:
        raise ValueError('immutable author test changed')
    return {'operation': 'in_memory_create_refresh_live_items_v1',
            'manifest_sha256': expected_manifest, 'test_sha256': expected_test,
            'source_modified': False, 'assertions_modified': False,
            'fabricated_rows': False, 'results': results,
            'status': 'experiment_only_not_green_or_approval', 'delivery_approval': False}


if __name__ == '__main__':
    print(json.dumps(run(Path('/snapshot'), os.environ['EXPECTED_MANIFEST'],
                         os.environ['EXPECTED_TEST']), sort_keys=True), flush=True)
