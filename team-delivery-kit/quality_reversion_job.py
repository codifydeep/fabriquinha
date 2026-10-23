"""First post-Green control: full frozen suite against the actual reviewed Red.

No mutation of files, fixture substitution, historical receipt conversion,
worker command or subset selection. Additional controls remain mandatory when
reversion fails to witness every criterion; partial coverage is never approval.
"""
import json
from pathlib import Path
try:
    import quality_lifecycle_v2 as quality
except ImportError:
    from broker import quality_lifecycle_v2 as quality
import quality_red_observation as observer
from r3_snapshot_probe import probe


def run(base,candidate,reviewed,plan,task,base_manifest,candidate_manifest,reviewed_manifest,evidence):
    require=quality.require
    require(quality.next_stage(plan,evidence)=='sensitivity')
    red=evidence['red'];green=evidence['green']
    require(task==green['task_id'] and candidate_manifest==green['manifest_sha256']
        and reviewed_manifest==red['manifest_sha256'] and candidate_manifest!=reviewed_manifest)
    base,candidate,reviewed=map(Path,(base,candidate,reviewed))
    observer.inputs(base,candidate,plan,base_manifest,candidate_manifest,frozen_tests=green['tests'])
    observer.inputs(base,reviewed,plan,base_manifest,reviewed_manifest,frozen_tests=green['tests'])
    current=json.loads((candidate/'manifest.json').read_bytes())['files']
    original=json.loads((reviewed/'manifest.json').read_bytes())['files']
    require(set(current)==set(original))
    changed=[]
    for path in original:
        before=observer._regular(reviewed,path);after=observer._regular(candidate,path)
        if path in plan['product_files']:
            require(before==observer._regular(base,path))
            if before!=after:changed.append(path)
        else:require(before==after)
    require(bool(changed))
    try:
        report=observer.run(base,reviewed,plan,task,base_manifest,reviewed_manifest,
            negative_context=dict(red=red,review=evidence['test_review'],green=green))
        facts=report['suite'];witnesses={(f['path'],f['method']) for f in facts['failures']}
        covered=sorted(c for c,tests in plan['criterion_tests'].items()
            if any((t['path'],t['method']) in witnesses for t in tests))
        missing=sorted(set(plan['criteria'])-set(covered));require(bool(covered))
        sensitivity=dict(operation='observed_sensitivity_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),green_sha256=quality.digest(green),
            positive_sha256=quality.digest(green),manifest_sha256=candidate_manifest,commit_sha=green['commit_sha'],
            controls=[dict(**facts,id='revert_product_to_reviewed_red',criteria=covered,changed_files=sorted(changed))])
        if not missing:quality.qualify_sensitivity(plan,{**evidence,'sensitivity':sensitivity})
        return dict(operation='post_green_reversion_observation_v2',sensitivity=sensitivity,coverage_complete=not missing,
            missing_criteria=missing,reviewed_manifest_sha256=reviewed_manifest,
            captured_output_sha256=report['captured_output_sha256'],snapshot_unchanged=True,tests_unchanged=True,
            execution_authorized=False,merge_authorized=False,delivery_approval=False)
    finally:
        probe(candidate,candidate_manifest);probe(reviewed,reviewed_manifest)
