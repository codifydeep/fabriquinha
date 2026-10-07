"""Fixed diagnostic intervention on a disposable copy, never an author delivery.

Run only offline, credential-free, with the original snapshot mounted read-only.
The controller chooses the experiment; there is no worker command/patch input.
Even a supported hypothesis does not produce Red or authorize another execution.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from r3_snapshot_probe import probe as verify_snapshot
import service_mode_harness_qualification as calibration

OLD = 'const after_ok = { text: after_ok_text, calls: after_ok_calls };'
NEW = 'const after_ok = { text: modeText(), calls: after_ok_calls };'
FAILED = {'test_exact_demo_object_yields_demo_environment', 'test_indicator_text_constants_are_exact'}


def template_node(tree):
    nodes = [n.value for n in tree.body if isinstance(n, ast.Assign) and
             any(isinstance(t, ast.Name) and t.id == calibration.TEMPLATE for t in n.targets)]
    if len(nodes) != 1 or not isinstance(nodes[0], ast.Constant) or not isinstance(nodes[0].value, str):
        raise ValueError('one literal observation harness required')
    return nodes[0]


def variant(source):
    """One unique controller anchor; complete remaining Python AST is identical."""
    before = ast.parse(source)
    node = template_node(before)
    if node.value.count(OLD) != 1 or source.count(OLD) != 1:
        raise ValueError('one exact stale observation anchor required')
    changed = source.replace(OLD, NEW, 1)
    after = ast.parse(changed)
    updated = template_node(after)
    if updated.value != node.value.replace(OLD, NEW, 1):
        raise ValueError('literal intervention drift')
    updated.value = node.value
    if ast.dump(before) != ast.dump(after):
        raise ValueError('non-harness AST changed')
    return changed


def observe(root, manifest):
    try:
        return calibration.run(root, manifest)
    except calibration.CalibrationRejected as error:
        return dict(status='rejected', phase=error.phase, facts=error.facts, delivery_approval=False)


def run(root, manifest):
    root = Path(root)
    identity = verify_snapshot(root, manifest)
    raw = (root / 'manifest.json').read_bytes()
    inventory = json.loads(raw)['files']
    source = (root / calibration.TEST).read_text()
    changed = variant(source)
    original = observe(root, manifest)
    positive = original.get('facts', {}).get('positive', {})
    if (original.get('status') != 'rejected' or original.get('phase') != 'positive_reference'
            or positive.get('tests', 0) < 15 or positive.get('failures') != 2
            or set(positive.get('failed_methods', [])) != FAILED
            or any(positive.get(k) != 0 for k in ('errors', 'skipped', 'expected_failures', 'unexpected_successes'))):
        raise ValueError('exact executed positive-reference failure required')
    verify_snapshot(root, manifest)
    with tempfile.TemporaryDirectory(prefix='observation-hypothesis-') as directory:
        candidate = Path(directory)
        for name in inventory:
            destination = candidate / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((root / name).read_bytes())
        data = changed.encode('utf-8')
        (candidate / calibration.TEST).write_bytes(data)
        entries = copy.deepcopy(inventory)
        entries[calibration.TEST] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        candidate_raw = json.dumps(dict(files=entries), sort_keys=True).encode()
        (candidate / 'manifest.json').write_bytes(candidate_raw)
        candidate_manifest = hashlib.sha256(candidate_raw).hexdigest()
        result = observe(candidate, candidate_manifest)
        verify_snapshot(candidate, candidate_manifest)
    verify_snapshot(root, manifest)
    return dict(operation='fixed_observation_hypothesis_v1',
                hypothesis='fresh_terminal_observation_after_async_settlement',
                original_manifest_sha256=identity['manifest_sha256'],
                original_test_sha256=inventory[calibration.TEST]['sha256'],
                variant_manifest_sha256=candidate_manifest,
                variant_test_sha256=entries[calibration.TEST]['sha256'],
                original=original, variant=result,
                status='supported' if result['status']=='passed' else 'refuted',
                inputs_unchanged=True, original_test_bodies_unchanged=True,
                diagnostic_copy_only=True, valid_red_green_receipt=False,
                author_retry_authorized=False, delivery_approval=False)


if __name__ == '__main__':
    import sys
    print(json.dumps(run(*sys.argv[1:]), sort_keys=True))
