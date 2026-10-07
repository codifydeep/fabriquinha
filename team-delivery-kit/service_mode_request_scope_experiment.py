"""Fixed causal experiment, never a submitted test edit or a Green receipt.

Execute only in an offline disposable sandbox with the snapshot read-only,
no credentials/socket and bounded writable /tmp. All test methods remain intact.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from r3_snapshot_probe import probe as verify_snapshot
from service_mode_harness_qualification import TEST,PRODUCT,CLASS,CASES,fixture,observed,validate_controls

ANCHOR='function loadCallsSince() { return calls.length - loadSliceBase.calls; }'
REPLACEMENT=("function loadCallsSince() { return calls.slice(loadSliceBase.calls).filter(function (c) { "
    "return c.method === 'GET' && c.url.split('?')[0] === '/service-mode'; }).length; }")


def change(template):
    if not isinstance(template,str) or template.count(ANCHOR)!=1:
        raise ValueError('one exact unscoped request-count helper required')
    return template.replace(ANCHOR,REPLACEMENT,1)


def supported(result):
    baseline=result['baseline'];scoped=result['scoped'];control=result['background_control']
    if (baseline['failures']!=3 or baseline['errors'] or baseline['skipped']
            or baseline['failed_methods']!=sorted([
                'test_client_requests_service_mode_once_at_load',
                'test_exactly_one_request_per_page_load_across_all_loads',
                'test_pending_probe_shows_checking_then_terminal_demo'])
            or scoped['tests']!=baseline['tests'] or scoped['tests']<15
            or any(scoped[k] for k in ('failures','errors','skipped','unexpected_successes','expected_failures'))
            or control['tests']!=scoped['tests']):
        raise ValueError('exact causal observations and complete unmodified tests required')
    validate_controls(control,result['negative_controls'])
    duplicate=result['actual_duplicate_control']
    if duplicate['tests']!=1 or duplicate['failures']!=1 or duplicate['errors'] or duplicate['skipped']:
        raise ValueError('actual duplicate probe must still fail by assertion')


def run(root,manifest):
    root=Path(root);verify_snapshot(root,manifest)
    spec=importlib.util.spec_from_file_location('request_scope_experiment',root/TEST)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cls=getattr(module,CLASS);module.NODE_TIMEOUT_SECONDS=3
    original=module.NODE_HARNESS_TEMPLATE;scoped=change(original)
    actual=(root/PRODUCT).read_text();original_path=module.APP_JS_PATH
    if not set(CASES.values())<=set(__import__('unittest').defaultTestLoader.getTestCaseNames(cls)):
        raise ValueError('all behavioral assertions required')
    try:
        baseline=observed(cls)
        module.NODE_HARNESS_TEMPLATE=scoped
        corrected=observed(cls)
        with tempfile.TemporaryDirectory(prefix='request-scope-experiment-') as directory:
            path=Path(directory)/'control.js';module.APP_JS_PATH=path
            # Three legitimate existing endpoints, not three mode requests.
            path.write_text("fetch('/service-status');fetch('/feedback');fetch('/feedback/summary');\n"+fixture('positive'))
            background=observed(cls);negatives={}
            for case,method in CASES.items():
                path.write_text(fixture(case));negatives[case]=observed(cls,method)
            path.write_text(actual+"\nfetch('/service-mode');\n")
            duplicate=observed(cls,CASES['duplicate_request'])
    finally:
        module.APP_JS_PATH=original_path;module.NODE_HARNESS_TEMPLATE=original
        verify_snapshot(root,manifest)
    result=dict(operation='immutable_request_scope_experiment_v1',manifest_sha256=manifest,
        test_sha256=hashlib.sha256((root/TEST).read_bytes()).hexdigest(),
        product_sha256=hashlib.sha256((root/PRODUCT).read_bytes()).hexdigest(),
        original_template_sha256=hashlib.sha256(original.encode()).hexdigest(),
        experimental_template_sha256=hashlib.sha256(scoped.encode()).hexdigest(),
        baseline=baseline,scoped=corrected,background_control=background,
        negative_controls=negatives,actual_duplicate_control=duplicate,
        snapshot_modified=False,assertions_modified=False,test_edits_authorized=False,
        delivery_approval=False,product_green=False,status='experiment_only_not_approved')
    supported(result)
    return result


if __name__=='__main__':
    import sys
    root=Path(sys.argv[1])
    manifest=sys.argv[2] if len(sys.argv)==3 else hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    print(json.dumps(run(root,manifest),sort_keys=True))
