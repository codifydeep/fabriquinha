"""Fixed indicator-write hypothesis on a disposable copy; never product Red."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

import service_mode_harness_qualification as calibration
import service_mode_timer_background_qualification as timers
from r3_snapshot_probe import probe as verify_snapshot

EDITS = (
    ('function makeElement(id, tagName) {', 'let indicatorWrites = 0;\nfunction makeElement(id, tagName) {'),
    ("set: function (v) { this._text = String(v); }",
     "set: function (v) { if (id === 'service-mode') { indicatorWrites++; } this._text = String(v); }"),
    ("set: function (v) { this._text = String(v); this.children = []; }",
     "set: function (v) { if (id === 'service-mode') { indicatorWrites++; } this._text = String(v); this.children = []; }"),
    ('const start = calls.length;\n  let hit = false;',
     'const start = calls.length;\n  const writeStart = indicatorWrites;\n  let hit = false;'),
    ('return hit;\n}', 'return hit || indicatorWrites > writeStart;\n}'),
)


def template(tree):
    nodes=[n.value for n in tree.body if isinstance(n,ast.Assign) and
        any(isinstance(t,ast.Name) and t.id==calibration.TEMPLATE for t in n.targets)]
    if len(nodes)!=1 or not isinstance(nodes[0],ast.Constant) or not isinstance(nodes[0].value,str):
        raise ValueError('one literal harness required')
    return nodes[0]


def variant(source):
    before=ast.parse(source);node=template(before);changed=source;expected=node.value
    for old,new in EDITS:
        if expected.count(old)!=1 or changed.count(old)!=1:
            raise ValueError('one exact controller anchor required')
        expected=expected.replace(old,new,1);changed=changed.replace(old,new,1)
    after=ast.parse(changed);updated=template(after)
    if updated.value!=expected:raise ValueError('literal intervention drift')
    updated.value=node.value
    if ast.dump(before)!=ast.dump(after):raise ValueError('non-harness AST changed')
    return changed


def observe(root,manifest):
    try:return timers.run(root,manifest)
    except calibration.CalibrationRejected as error:
        return dict(status='rejected',phase=error.phase,facts=error.facts,delivery_approval=False)


def baseline(root):
    spec=importlib.util.spec_from_file_location('diagnostic_baseline',root/calibration.TEST)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.NODE_TIMEOUT_SECONDS=3
    return calibration.observed(getattr(module,calibration.CLASS))


def run(root,manifest):
    root=Path(root);identity=verify_snapshot(root,manifest)
    inventory=json.loads((root/'manifest.json').read_bytes())['files']
    source=(root/calibration.TEST).read_text();changed=variant(source)
    original=observe(root,manifest)
    facts=original.get('facts',{});positive=facts.get('positive',{})
    defects=facts.get('negative_controls',{})
    required=set(calibration.CASES)|set(timers.INDICATOR_TIMERS)
    if (original.get('status')!='rejected' or original.get('phase')!='background_timer_control'
            or positive.get('tests',0)<15 or any(positive.get(k)!=0 for k in
                ('failures','errors','skipped','unexpected_successes','expected_failures'))
            or set(defects)!=required):raise ValueError('exact measured timer rejection required')
    missed=set()
    for case,v in defects.items():
        if v.get('tests')!=1 or any(v.get(k)!=0 for k in ('errors','skipped','unexpected_successes','expected_failures')):
            raise ValueError('executed assertion controls required')
        if v.get('failures')==0:missed.add(case)
        elif v.get('failures')!=1:raise ValueError('one assertion per negative control required')
    if missed!={'indicator_interval','indicator_timeout'}:raise ValueError('exact indicator-only defects required')
    verify_snapshot(root,manifest)
    with tempfile.TemporaryDirectory(prefix='indicator-write-hypothesis-') as directory:
        candidate=Path(directory)
        for name in inventory:
            destination=candidate/name;destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes((root/name).read_bytes())
        data=changed.encode();(candidate/calibration.TEST).write_bytes(data)
        entries=copy.deepcopy(inventory)
        entries[calibration.TEST]=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        raw=json.dumps(dict(files=entries),sort_keys=True).encode()
        (candidate/'manifest.json').write_bytes(raw);candidate_manifest=hashlib.sha256(raw).hexdigest()
        result=observe(candidate,candidate_manifest)
        actual=baseline(candidate);verify_snapshot(candidate,candidate_manifest)
    verify_snapshot(root,manifest)
    return dict(operation='fixed_indicator_write_hypothesis_v1',hypothesis='attribute_indicator_writes_without_fetch',
        original_manifest_sha256=identity['manifest_sha256'],variant_manifest_sha256=candidate_manifest,
        original_test_sha256=inventory[calibration.TEST]['sha256'],variant_test_sha256=entries[calibration.TEST]['sha256'],
        original=original,variant=result,baseline_observation=actual,
        variant_file_bytes=len(data),fits_existing_file_limit=len(data)<=32768,
        status='supported' if result.get('status')=='passed' else 'refuted',
        inputs_unchanged=True,original_test_bodies_unchanged=True,diagnostic_copy_only=True,
        valid_red_green_receipt=False,author_retry_authorized=False,delivery_approval=False)


if __name__=='__main__':
    import sys
    print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
